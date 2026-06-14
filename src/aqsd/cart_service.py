from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Callable

from loguru import logger

from aqsd.cart_store import CartStore
from aqsd.models import Cart, CartEvent, CartItem
from aqsd.qbittorrent import QBittorrentClient
from aqsd.utils import build_task_tag, fix_magnet_name

PROBE_DURATION_SECONDS = 180
PROBE_MIN_SPEED_KBPS = 10
DEAD_CHECK_AFTER_MINUTES = 30
MONITOR_INTERVAL_SECONDS = 60


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cart_item_from_candidate(candidate: dict) -> CartItem:
    parsed = candidate.get("parsed", {}) if isinstance(candidate, dict) else {}
    return CartItem(
        title=candidate.get("title", ""),
        magnet=candidate.get("magnet"),
        url=candidate.get("url", ""),
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
    ) -> None:
        self._store = store
        self._qb_factory = qb_factory
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
        if cart.active_hash:
            try:
                qb = self._qb_factory()
                qb.delete_torrent(cart.active_hash, delete_files=True)
            except Exception as exc:
                logger.warning("Failed to delete qB torrent for cart {}: {}", cart_id, exc)
        self._store.delete(cart_id)
        logger.info("Cart {} deleted", cart_id)
        return True

    # ── probe & start ──────────────────────────────────────

    def start_cart(self, cart_id: str) -> Cart | None:
        cart = self._store.get(cart_id)
        if cart is None or cart.status not in ("idle", "exhausted"):
            return None
        if not cart.items:
            return None

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
                return

            attempts: dict[str, CartItem] = {}
            for item in remaining:
                tag = build_task_tag(cart.anime_name, cart.episode)
                download_url = fix_magnet_name(item.magnet or item.url, item.title)
                try:
                    qb.add_torrent(
                        download_url,
                        category=None,
                        save_path=None,
                        tags=tag,
                    )
                    attempts[tag] = item
                except Exception as exc:
                    logger.warning("Probe add failed for {}: {}", item.title, exc)

            if not attempts:
                cart.status = "idle"
                cart.events.append(CartEvent(
                    timestamp=_now_iso(),
                    type="probe_end",
                    message="probe 失败：无法添加任何候选到 qB",
                ))
                self._store.save(cart)
                return

            time.sleep(PROBE_DURATION_SECONDS)

            by_tag = self._list_qb_torrents_by_tag(qb)
            best_tag: str | None = None
            best_score = float("-inf")

            for tag, item in attempts.items():
                torrent = by_tag.get(tag)
                if torrent is None:
                    continue
                score = self._probe_score(torrent)
                if score > best_score:
                    best_score = score
                    best_tag = tag

            selected = attempts.get(best_tag) if best_tag else None
            # delete losers
            for tag in attempts:
                if tag == best_tag:
                    continue
                torrent = by_tag.get(tag)
                if torrent and torrent.get("hash"):
                    try:
                        qb.delete_torrent(torrent["hash"], delete_files=True)
                    except Exception as exc:
                        logger.warning("Probe loser delete failed: {}", exc)

            if selected is None:
                cart.status = "idle"
                cart.events.append(CartEvent(
                    timestamp=_now_iso(),
                    type="probe_end",
                    message="probe 结束：无候选获得连接，请稍后重试",
                ))
                self._store.save(cart)
                return

            if selected.info_hash:
                cart.tried_hashes.append(selected.info_hash)
            cart.active_hash = self._get_hash_for_tag(qb, best_tag) if best_tag else None
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

    @staticmethod
    def _probe_score(torrent: dict) -> float:
        speed_kbps = float(torrent.get("dlspeed", 0) or 0) / 1024
        connected_seeds = int(torrent.get("num_seeds", 0) or 0)
        peers = int(torrent.get("num_leechs", torrent.get("num_peers", 0)) or 0)
        availability = float(torrent.get("availability", 0) or 0)
        progress = float(torrent.get("progress", 0) or 0)

        speed_score = speed_kbps if speed_kbps >= PROBE_MIN_SPEED_KBPS else speed_kbps * 0.1
        if speed_score < 0.01:
            speed_score = 0
        return speed_score + connected_seeds * 10 + peers * 2 + availability * 5 + progress * 100_000

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
            if torrent is None:
                cart.status = "done"
                cart.events.append(CartEvent(
                    timestamp=_now_iso(),
                    type="done",
                    message="下载完成或已从 qB 移除",
                ))
                self._store.save(cart)
                continue

            if self._is_dead(torrent):
                self._handle_dead(cart, qb)

    def _is_dead(self, torrent: dict) -> bool:
        state = (torrent.get("state") or "").lower()
        if state in ("error", "missingfiles"):
            return True

        progress = float(torrent.get("progress", 0) or 0)
        added_on = int(torrent.get("added_on", 0) or 0)
        minutes_since_add = (time.time() - added_on) / 60 if added_on else 0

        if progress < 0.001 and minutes_since_add >= DEAD_CHECK_AFTER_MINUTES:
            return True

        if state == "stalleddl" and progress < 0.001 and minutes_since_add >= DEAD_CHECK_AFTER_MINUTES:
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
    def _list_qb_torrents_by_tag(qb: QBittorrentClient) -> dict[str, dict]:
        by_tag: dict[str, dict] = {}
        try:
            for torrent in qb.list_torrents():
                raw_tags = torrent.get("tags", "") or ""
                for tag in [t.strip() for t in raw_tags.split(",") if t.strip()]:
                    by_tag[tag] = torrent
        except Exception:
            pass
        return by_tag

    @staticmethod
    def _get_hash_for_tag(qb: QBittorrentClient, tag: str) -> str | None:
        try:
            for torrent in qb.list_torrents():
                raw_tags = torrent.get("tags", "") or ""
                if tag in [t.strip() for t in raw_tags.split(",") if t.strip()]:
                    return torrent.get("hash")
        except Exception:
            pass
        return None
