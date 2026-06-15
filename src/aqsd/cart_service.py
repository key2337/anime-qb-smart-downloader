from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Callable

from loguru import logger

from aqsd.cart_store import CartStore
from aqsd.database import Database
from aqsd.models import Candidate, Cart, CartEvent, CartItem
from aqsd.qbittorrent import QBittorrentClient
from aqsd.utils import fix_magnet_name

PROBE_DURATION_SECONDS = 20

DEAD_CHECK_AFTER_MINUTES = 30
MONITOR_INTERVAL_SECONDS = 60
METADL_TIMEOUT_MINUTES = 10


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _cart_item_from_candidate(candidate: dict) -> CartItem:
    parsed = candidate.get("parsed", {}) if isinstance(candidate, dict) else {}
    return CartItem(
        title=candidate.get("title", ""),
        magnet=candidate.get("magnet") or "",
        url=candidate.get("url") or "",
        source=candidate.get("source", ""),
        seeders=candidate.get("seeders", 0),
        score=candidate.get("score", 0),
        info_hash=candidate.get("info_hash"),
        group=parsed.get("group"),
        resolution=parsed.get("resolution"),
        subtitle_type=parsed.get("subtitle_type"),
        is_batch=parsed.get("is_batch", False),
        is_raw=parsed.get("is_raw", False),
        episode=parsed.get("episode"),
        season=parsed.get("season"),
    )


class CartService:
    def __init__(
        self,
        store: CartStore,
        qb_factory: Callable[[], QBittorrentClient],
        db: Database | None = None,
    ) -> None:
        self._store = store
        self._qb_factory = qb_factory
        self._db = db
        self._probe_lock = threading.Lock()
        self._monitor_running = False
        self._monitor_thread: threading.Thread | None = None

    # ── cart CRUD ──────────────────────────────────────────

    def create_cart(self, anime_name: str, episode: str, items: list[dict]) -> Cart:
        cart = Cart(
            cart_id=uuid.uuid4().hex[:12],
            anime_name=anime_name,
            episode=episode or "",
            items=[_cart_item_from_candidate(item) for item in items],
            created_at=_now_iso(),
        )
        cart.events.append(CartEvent(
            timestamp=_now_iso(),
            type="created",
            message=f"购物车创建：{anime_name}，{len(cart.items)} 个候选",
        ))
        self._store.save(cart)
        logger.info("Cart {} created: {} ({} items)", cart.cart_id, anime_name, len(cart.items))
        return cart

    def add_items(self, cart_id: str, items: list[dict]) -> Cart | None:
        cart = self._store.get(cart_id)
        if cart is None:
            return None
        new_items = [_cart_item_from_candidate(item) for item in items]
        existing_hashes = {item.info_hash for item in cart.items if item.info_hash}
        for item in new_items:
            if item.info_hash and item.info_hash in existing_hashes:
                continue
            cart.items.append(item)
            if item.info_hash:
                existing_hashes.add(item.info_hash)
        self._store.save(cart)
        return cart

    def get_cart(self, cart_id: str) -> Cart | None:
        return self._store.get(cart_id)

    def list_carts(self) -> list[Cart]:
        return self._store.list_all()

    def delete_cart(self, cart_id: str) -> bool:
        cart = self._store.get(cart_id)
        if cart is None:
            return False
        try:
            qb = self._qb_factory()
            # Delete the active/downloading torrent if present
            if cart.active_hash:
                try:
                    qb.delete_torrent(cart.active_hash, delete_files=True)
                except Exception as exc:
                    logger.warning("Failed to delete qB torrent for cart {}: {}", cart_id, exc)
            # For probing/idle carts, clean up any probe-added torrents
            item_hashes = {
                item.info_hash.casefold()
                for item in cart.items
                if item.info_hash
            }
            if item_hashes:
                for t in qb.list_torrents():
                    h = (t.get("hash") or "").strip().casefold()
                    if h in item_hashes:
                        try:
                            qb.delete_torrent(t["hash"], delete_files=True)
                            logger.info("Cleaned up probe torrent {} for deleted cart {}", h[:12], cart_id)
                        except Exception as exc:
                            logger.warning("Failed to delete probe torrent {}: {}", h[:12], exc)
        except Exception as exc:
            logger.warning("Failed to clean up qB torrents for cart {}: {}", cart_id, exc)
        self._store.delete(cart_id)
        logger.info("Cart {} deleted", cart_id)
        self._process_queue()
        return True

    # ── pause / resume ─────────────────────────────────────

    def pause_cart(self, cart_id: str) -> Cart | None:
        cart = self._store.get(cart_id)
        if cart is None or cart.status not in ("downloading",):
            return None
        if cart.active_hash:
            try:
                qb = self._qb_factory()
                qb.pause_torrents(cart.active_hash)
            except Exception as exc:
                logger.warning("Failed to pause qB torrent for cart {}: {}", cart_id, exc)
        cart.status = "paused"
        cart.events.append(CartEvent(
            timestamp=_now_iso(),
            type="paused",
            message="用户暂停下载",
        ))
        self._store.save(cart)
        logger.info("Cart {} paused", cart_id)
        self._process_queue()
        return cart

    def resume_cart(self, cart_id: str) -> Cart | None:
        cart = self._store.get(cart_id)
        if cart is None or cart.status != "paused":
            return None
        if self._has_other_active_cart(cart_id):
            logger.warning("Cannot resume cart {}: another cart is already active", cart_id)
            return None
        if cart.active_hash:
            try:
                qb = self._qb_factory()
                qb.resume_torrents(cart.active_hash)
            except Exception as exc:
                logger.warning("Failed to resume qB torrent for cart {}: {}", cart_id, exc)
        cart.status = "downloading"
        cart.events.append(CartEvent(
            timestamp=_now_iso(),
            type="resumed",
            message="用户恢复下载",
        ))
        self._store.save(cart)
        logger.info("Cart {} resumed", cart_id)
        return cart

    # ── probe & start ──────────────────────────────────────

    def recover_probing_carts(self) -> int:
        """Reset probing carts to idle after a restart (user restarts manually)."""
        count = 0
        for cart in self._store.list_by_status("probing"):
            cart.status = "idle"
            cart.events.append(CartEvent(
                timestamp=_now_iso(),
                type="recover",
                message="服务重启，请手动设置探测时长后重新开始",
            ))
            self._store.save(cart)
            count += 1
        return count

    def _has_other_active_cart(self, cart_id: str) -> bool:
        for cart in self._store.list_all():
            if cart.cart_id != cart_id and cart.status in ("probing", "downloading"):
                return True
        return False

    def start_cart(self, cart_id: str, probe_duration_seconds: int = 20) -> Cart | None:
        cart = self._store.get(cart_id)
        if cart is None or cart.status not in ("idle", "exhausted"):
            return None
        if not cart.items:
            return None
        if self._has_other_active_cart(cart_id):
            logger.warning("Cannot start cart {}: another cart is already active", cart_id)
            return None

        cart.probe_duration_seconds = probe_duration_seconds
        cart.status = "probing"
        cart.events.append(CartEvent(
            timestamp=_now_iso(),
            type="probe_start",
            message=f"开始 probe {len(cart.items)} 个候选",
        ))
        self._store.save(cart)

        thread = threading.Thread(target=self._run_probe, args=(cart_id,), daemon=True)
        thread.start()
        return cart

    def _run_probe(self, cart_id: str) -> None:
        with self._probe_lock:
            cart = self._store.get(cart_id)
            if cart is None or cart.status != "probing":
                return

            qb = self._qb_factory()
            remaining = [
                item for item in cart.items
                if item.info_hash not in cart.tried_hashes
            ]
            if not remaining:
                cart.status = "exhausted"
                cart.events.append(CartEvent(
                    timestamp=_now_iso(),
                    type="exhausted",
                    message="所有候选已尝试完毕，无可用资源",
                ))
                self._store.save(cart)
                self._process_queue()
                return

            attempts: dict[str, CartItem] = {}
            try:
                for item in remaining:
                    if not item.info_hash:
                        continue
                    download_url = fix_magnet_name(item.magnet or item.url, item.title)
                    if not download_url:
                        continue
                    try:
                        qb.add_torrent(download_url, paused=True)
                        attempts[item.info_hash.casefold()] = item
                    except Exception as exc:
                        logger.warning("Probe add failed for {}: {}", item.title, exc)

                if not attempts:
                    cart.status = "idle"
                    cart.events.append(CartEvent(
                        timestamp=_now_iso(),
                        type="probe_end",
                        message="probe 失败：无可用 info_hash 候选",
                    ))
                    self._store.save(cart)
                    self._process_queue()
                    return

                time.sleep(2)  # let qB process the additions

                # Serial probe: test each candidate one at a time
                by_hash = _build_qb_torrent_map(qb)
                scores: dict[str, float] = {}
                for info_hash, item in attempts.items():
                    torrent = by_hash.get(info_hash)
                    if not torrent or not torrent.get("hash"):
                        scores[info_hash] = 0.0
                        continue

                    try:
                        qb.resume_torrents(torrent["hash"])
                    except Exception as exc:
                        logger.warning("Probe resume failed for {}: {}", item.title, exc)
                        scores[info_hash] = 0.0
                        continue

                    logger.info("Probe: testing {} for {}s", item.title, cart.probe_duration_seconds)
                    time.sleep(cart.probe_duration_seconds)

                    # Re-fetch torrent state
                    by_hash = _build_qb_torrent_map(qb)
                    updated = by_hash.get(info_hash)
                    if updated:
                        scores[info_hash] = self._probe_score(updated)
                        speed_kbps = float(updated.get("dlspeed", 0) or 0) / 1024
                        seeds = int(updated.get("num_seeds", 0) or 0)
                        cart.events.append(CartEvent(
                            timestamp=_now_iso(),
                            type="probe_candidate",
                            message=f"探测：{item.title} — 得分 {scores[info_hash]:.0f}（速度 {speed_kbps:.0f} KB/s，种子 {seeds}）",
                        ))
                        self._store.save(cart)
                    else:
                        scores[info_hash] = 0.0
                        cart.events.append(CartEvent(
                            timestamp=_now_iso(),
                            type="probe_candidate",
                            message=f"探测：{item.title} — 未找到 torrent",
                        ))
                        self._store.save(cart)

                    # Pause so next candidate gets full bandwidth
                    try:
                        qb.pause_torrents(torrent["hash"])
                    except Exception as exc:
                        logger.warning("Probe pause failed for {}: {}", item.title, exc)

                # Pick winner
                best_hash: str | None = None
                best_score = float("-inf")
                for info_hash, score in scores.items():
                    if score > best_score:
                        best_score = score
                        best_hash = info_hash

                selected = attempts.get(best_hash) if best_hash else None

                if selected is None or best_score <= 0:
                    for info_hash in attempts:
                        torrent = by_hash.get(info_hash)
                        if torrent and torrent.get("hash"):
                            try:
                                qb.delete_torrent(torrent["hash"], delete_files=True)
                            except Exception as exc:
                                logger.warning("Probe cleanup failed: {}", exc)
                    cart.status = "idle"
                    if selected is None:
                        msg = "probe 结束：无候选获得连接"
                    else:
                        msg = f"probe 结束：所有候选无速度（最佳得分 {best_score:.0f}）"
                    cart.events.append(CartEvent(
                        timestamp=_now_iso(),
                        type="probe_end",
                        message=msg,
                    ))
                    self._store.save(cart)
                    self._process_queue()
                    return

                # Delete losers
                for info_hash in attempts:
                    if info_hash == best_hash:
                        continue
                    torrent = by_hash.get(info_hash)
                    if torrent and torrent.get("hash"):
                        try:
                            qb.delete_torrent(torrent["hash"], delete_files=True)
                        except Exception as exc:
                            logger.warning("Probe loser delete failed: {}", exc)

                # Resume winner
                winner_torrent = by_hash.get(best_hash)
                if winner_torrent and winner_torrent.get("hash"):
                    try:
                        qb.resume_torrents(winner_torrent["hash"])
                    except Exception as exc:
                        logger.warning("Probe winner resume failed: {}", exc)

                if selected.info_hash:
                    cart.tried_hashes.append(selected.info_hash)
                cart.active_hash = best_hash
                cart.active_title = selected.title
                cart.fallback_count = 0
                cart.status = "downloading"
                cart.events.append(CartEvent(
                    timestamp=_now_iso(),
                    type="probe_end",
                    message=f"选中：{selected.title}（得分 {best_score:.0f}）",
                ))
                self._store.save(cart)
                logger.info("Cart {} probe complete: selected {}", cart_id, selected.title)
            except Exception:
                logger.exception("Probe for cart {} crashed", cart_id)
                cart = self._store.get(cart_id)
                if cart and cart.status == "probing":
                    cart.status = "idle"
                    cart.events.append(CartEvent(
                        timestamp=_now_iso(),
                        type="probe_end",
                        message="probe 异常退出，回退到 idle",
                    ))
                    self._store.save(cart)
                    self._process_queue()

    @staticmethod
    def _probe_score(torrent: dict) -> float:
        speed_kbps = float(torrent.get("dlspeed", 0) or 0) / 1024
        state = (torrent.get("state") or "").lower()

        # metaDL = metadata not resolved yet — unusable, exclude
        if state == "metadl":
            return -1.0

        connected_seeds = int(torrent.get("num_seeds", 0) or 0)
        peers = int(torrent.get("num_leechs", torrent.get("num_peers", 0)) or 0)
        availability = float(torrent.get("availability", 0) or 0)
        progress = float(torrent.get("progress", 0) or 0)

        # Speed is the primary signal; healthy torrents deliver 100+ KB/s
        speed_score = speed_kbps * 1
        # Seeds/peers indicate swarm health; availability = can complete
        # Progress is a minimal tiebreaker (1% = 0.5 pts)
        return speed_score + connected_seeds * 3 + peers * 1 + availability * 10 + progress * 50

    # ── queue ──────────────────────────────────────────────

    def enqueue_cart(self, anime_name: str, episode: str, items: list[dict]) -> Cart:
        """Create a cart with 'waiting' status and process the queue."""
        cart = self.create_cart(anime_name, episode, items)
        cart.status = "waiting"
        cart.events.append(CartEvent(
            timestamp=_now_iso(),
            type="enqueued",
            message="进入等待队列",
        ))
        self._store.save(cart)
        self._process_queue()
        return cart

    def _process_queue(self) -> None:
        """If no cart is probing/downloading, start the oldest waiting cart."""
        active = any(
            c.status in ("probing", "downloading")
            for c in self._store.list_all()
        )
        if active:
            return
        waiting = sorted(
            [c for c in self._store.list_all() if c.status == "waiting"],
            key=lambda c: c.created_at,
        )
        if waiting:
            self.start_cart(waiting[0].cart_id)

    # ── monitor ────────────────────────────────────────────

    def start_monitor(self) -> None:
        if self._monitor_running:
            return
        self._monitor_running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("Cart monitor started")

    def stop_monitor(self) -> None:
        self._monitor_running = False

    def _monitor_loop(self) -> None:
        while self._monitor_running:
            try:
                self.monitor()
            except Exception:
                logger.exception("Cart monitor iteration failed")
            time.sleep(MONITOR_INTERVAL_SECONDS)

    def monitor(self) -> None:
        carts = self._store.list_by_status("downloading")
        if not carts:
            return

        qb = self._qb_factory()
        try:
            torrents = {t.get("hash", ""): t for t in qb.list_torrents()}
        except Exception as exc:
            logger.warning("Monitor: failed to list qB torrents: {}", exc)
            return

        for cart in carts:
            if not cart.active_hash:
                continue
            torrent = torrents.get(cart.active_hash)
            if torrent is None or self._is_completed(torrent):
                cart.status = "done"
                cart.events.append(CartEvent(
                    timestamp=_now_iso(),
                    type="done",
                    message="下载完成",
                ))
                self._store.save(cart)
                if self._db and cart.anime_name and cart.episode:
                    self._db.mark_downloaded(Candidate(
                        title=cart.anime_name,
                        anime_name=cart.anime_name,
                        episode=cart.episode,
                        url="",
                        source="",
                    ))
                    logger.info("Marked {}/{} as downloaded", cart.anime_name, cart.episode)
                self._process_queue()
                continue

            if self._is_dead(torrent):
                self._handle_dead(cart, qb)

    @staticmethod
    def _is_completed(torrent: dict) -> bool:
        state = (torrent.get("state") or "").lower()
        progress = float(torrent.get("progress", 0) or 0)
        return progress >= 1.0 or state.endswith("up")

    def _is_dead(self, torrent: dict) -> bool:
        state = (torrent.get("state") or "").lower()
        if state in ("error", "missingfiles"):
            return True

        if state in ("pauseddl", "pausedmetadl"):
            return False

        added_on = int(torrent.get("added_on", 0) or 0)
        minutes_since_add = (time.time() - added_on) / 60 if added_on else 0

        # Magnet stuck in metadata download — DHT unreachable
        if state == "metadl" and minutes_since_add >= METADL_TIMEOUT_MINUTES:
            return True

        progress = float(torrent.get("progress", 0) or 0)

        if progress < 0.001 and minutes_since_add >= DEAD_CHECK_AFTER_MINUTES:
            return True

        return False

    def _handle_dead(self, cart: Cart, qb: QBittorrentClient) -> None:
        cart.fallback_count += 1
        cart.events.append(CartEvent(
            timestamp=_now_iso(),
            type="fallback",
            message=f"死种检测：{cart.active_title}，回退 {cart.fallback_count}/{cart.max_fallbacks}",
        ))
        logger.warning("Cart {} dead torrent detected: {}", cart.cart_id, cart.active_title)

        if cart.active_hash:
            try:
                qb.delete_torrent(cart.active_hash, delete_files=True)
            except Exception as exc:
                logger.warning("Failed to delete dead torrent: {}", exc)
        cart.active_hash = None
        cart.active_title = None

        if cart.fallback_count >= cart.max_fallbacks:
            cart.status = "exhausted"
            cart.events.append(CartEvent(
                timestamp=_now_iso(),
                type="exhausted",
                message=f"已达到最大回退次数（{cart.max_fallbacks}），放弃",
            ))
            self._store.save(cart)
            self._process_queue()
            return

        remaining = [
            item for item in cart.items
            if item.info_hash not in cart.tried_hashes
        ]
        if not remaining:
            cart.status = "exhausted"
            cart.events.append(CartEvent(
                timestamp=_now_iso(),
                type="exhausted",
                message="所有候选已尝试完毕",
            ))
            self._store.save(cart)
            self._process_queue()
            return

        if self._has_other_active_cart(cart.cart_id):
            cart.status = "idle"
            cart.events.append(CartEvent(
                timestamp=_now_iso(),
                type="fallback",
                message="有其他购物车正在运行，等待中",
            ))
            self._store.save(cart)
            self._process_queue()
            return

        cart.status = "probing"
        cart.events.append(CartEvent(
            timestamp=_now_iso(),
            type="probe_start",
            message=f"回退 probe：{len(remaining)} 个剩余候选",
        ))
        self._store.save(cart)
        thread = threading.Thread(target=self._run_probe, args=(cart.cart_id,), daemon=True)
        thread.start()

    # ── helpers ─────────────────────────────────────────────

    @staticmethod
    def _normalize_hash(hash_value: str | None) -> str | None:
        if not hash_value:
            return None
        return hash_value.strip().casefold()


def _build_qb_torrent_map(qb: QBittorrentClient) -> dict[str, dict]:
    by_hash: dict[str, dict] = {}
    try:
        for torrent in qb.list_torrents():
            h = (torrent.get("hash") or "").strip().casefold()
            if h:
                by_hash[h] = torrent
    except Exception:
        pass
    return by_hash
