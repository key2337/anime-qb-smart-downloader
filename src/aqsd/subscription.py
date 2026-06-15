"""Anime subscription manager: periodic RSS checks feeding into CartService."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from loguru import logger

from aqsd.config import AppConfig, SubscriptionSettings
from aqsd.database import Database
from aqsd.matcher import match_candidate
from aqsd.mikan import enrich_candidates_with_info_hash
from aqsd.models import Candidate, SubscriptionCheckResult
from aqsd.parser import parse_candidate
from aqsd.rss import build_keyword_rss_url, fetch_rss, _is_mikan_url
from aqsd.scorer import score_candidate


class SubscriptionManager:
    def __init__(
        self,
        config: AppConfig,
        db: Database,
        cart_service,
    ) -> None:
        self._config = config
        self._db = db
        self._cart_service = cart_service
        self._running = False
        self._thread: threading.Thread | None = None
        self._check_lock = threading.Lock()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._check_loop, daemon=True)
        self._thread.start()
        logger.info("SubscriptionManager started (interval={}s)", self._config.app.interval_seconds)

    def stop(self) -> None:
        self._running = False

    def check_all(self) -> dict[str, SubscriptionCheckResult]:
        """Run a full subscription check cycle. Returns results keyed by subscription name."""
        results: dict[str, SubscriptionCheckResult] = {}
        with self._check_lock:
            for rule in self._merged_subscriptions():
                if not rule.enabled:
                    continue
                try:
                    result = self._check_one(rule)
                    results[rule.name] = result
                except Exception as exc:
                    logger.exception("Subscription check failed for {}", rule.name)
                    results[rule.name] = SubscriptionCheckResult(
                        subscription_name=rule.name,
                        errors=[str(exc)],
                    )
        return results

    def check_one_by_id(self, sub_id: int) -> SubscriptionCheckResult | None:
        row = self._db.get_subscription(sub_id)
        if row is None:
            return None
        if not row["enabled"]:
            return None
        # Try config rule first (has richer settings), fall back to DB row
        for rule in self._config.subscriptions:
            if rule.name == row["name"]:
                with self._check_lock:
                    return self._check_one(rule)
        rule = SubscriptionSettings(
            name=row["name"],
            enabled=row["enabled"],
            source_name=row["source_name"] or "",
            match_name=row["match_name"] or "",
            episode_offset=row["episode_offset"] or 0,
        )
        with self._check_lock:
            return self._check_one(rule)

    # ── private ──────────────────────────────────────────

    def _merged_subscriptions(self) -> list:
        """Return config subscriptions + DB-only subscriptions (by name)."""
        from aqsd.config import SubscriptionSettings
        merged: dict[str, SubscriptionSettings] = {}
        # Config first (authoritative for matching rules)
        for rule in self._config.subscriptions:
            merged[rule.name] = rule
        # DB entries not in config
        for row in self._db.list_subscriptions():
            if row["name"] not in merged:
                merged[row["name"]] = SubscriptionSettings(
                    name=row["name"],
                    enabled=row["enabled"],
                    source_name=row["source_name"] or "",
                    match_name=row["match_name"] or "",
                    episode_offset=row["episode_offset"] or 0,
                )
        return list(merged.values())

    def _check_loop(self) -> None:
        while self._running:
            try:
                self.check_all()
            except Exception:
                logger.exception("SubscriptionManager check cycle failed")
            time.sleep(self._config.app.interval_seconds)

    def _check_one(self, sub_rule) -> SubscriptionCheckResult:
        from aqsd.config import SubscriptionSettings
        sub = sub_rule if isinstance(sub_rule, SubscriptionSettings) else SubscriptionSettings(**sub_rule)
        result = SubscriptionCheckResult(subscription_name=sub.name)

        # Resolve source
        source = _find_source(self._config, sub.source_name)
        if source is None:
            result.errors.append(f"RSS source not found: {sub.source_name}")
            return result

        # Resolve anime rule; if not found, create a basic one from subscription name
        anime_rule = _find_anime_rule(self._config, sub.match_name)
        if anime_rule is None:
            from aqsd.config import AnimeRuleSettings
            anime_rule = AnimeRuleSettings(
                name=sub.match_name or sub.name,
                aliases=[sub.name] if sub.match_name else [],
                profile="fastest",
            )

        default_category = self._config.qb.default_category
        default_save_path = self._config.qb.default_save_path

        # Fetch RSS (use keyword for dmhy-style sources, full feed for Mikan)
        try:
            source_url = source.url
            keyword = None
            if "dmhy.org" in source_url and not _is_mikan_url(source_url):
                keyword = sub.match_name or sub.name
            items = fetch_rss(source, keyword=keyword)
        except Exception as exc:
            result.errors.append(f"RSS fetch failed: {exc}")
            return result
        result.rss_entries = len(items)

        # Parse, match, score
        matched: list[Candidate] = []
        for item in items:
            if not item.url:
                continue
            candidate = parse_candidate(item)
            candidate = match_candidate(
                candidate,
                [anime_rule],
                self._config.profiles,
                default_category,
                default_save_path,
            )
            if candidate is None or not candidate.anime_name or not candidate.episode:
                continue
            score_candidate(candidate, anime_rule, self._config.profiles.get(anime_rule.profile, {}))
            matched.append(candidate)
        result.matched = len(matched)

        # Filter already-downloaded
        new: list[Candidate] = []
        for c in matched:
            if self._db.already_downloaded(c.anime_name, c.episode):
                continue
            new.append(c)

        # Episode offset filter — skip episodes ≤ threshold
        threshold = sub.episode_offset
        if threshold > 0:
            before = len(new)
            filtered: list[Candidate] = []
            for c in new:
                try:
                    if int(c.episode or "") > threshold:
                        filtered.append(c)
                except ValueError:
                    filtered.append(c)
            new = filtered
            logger.info("Episode offset filter: {} -> {} candidates (threshold={})",
                        before, len(new), threshold)

        # Enrich info_hash for Mikan sources
        if _is_mikan_url(source.url):
            enriched = enrich_candidates_with_info_hash(new)
            if enriched:
                logger.info("Subscription {} enriched {} Mikan candidates with info_hash", sub.name, enriched)

        # Group by (anime_name, episode), keep top N per episode
        by_episode: dict[tuple[str, str], list[Candidate]] = {}
        for c in new:
            key = (c.anime_name or "", c.episode or "")
            by_episode.setdefault(key, []).append(c)

        # Sort each group by score desc, keep top 5
        for key in by_episode:
            by_episode[key].sort(key=lambda c: (c.score, c.seeders), reverse=True)
            by_episode[key] = by_episode[key][:5]

        # Check for existing active carts to avoid duplicates
        active_carts = self._cart_service.list_carts()
        active_episodes: set[tuple[str, str]] = set()
        for cart in active_carts:
            if cart.status in ("idle", "probing", "downloading"):
                if cart.anime_name and cart.episode:
                    active_episodes.add((cart.anime_name, cart.episode))

        # Create cart for the first new episode (limit 1 per check)
        default_anime_name = sub.match_name or sub.name
        sorted_episodes = sorted(by_episode.keys(), key=lambda k: _episode_sort_key(k[1]))
        for (anime_name, episode) in sorted_episodes:
            if (anime_name, episode) in active_episodes:
                logger.debug("Skipping {}/{}: already has active cart", anime_name, episode)
                continue
            candidates = by_episode[(anime_name, episode)]
            items = [_candidate_to_cart_dict(c) for c in candidates]
            try:
                cart = self._cart_service.create_cart(anime_name, episode, items)
                self._cart_service.start_cart(cart.cart_id)
                result.new_episodes.append(episode)
                result.created_carts.append(cart.cart_id)
                logger.info("Subscription {} created cart {} for {}/{}",
                            sub.name, cart.cart_id, anime_name, episode)
                break  # only one cart per check
            except Exception as exc:
                result.errors.append(f"Cart creation failed for {anime_name}/{episode}: {exc}")
                logger.warning("Failed to create cart for {}/{}: {}", anime_name, episode, exc)

        # Ensure DB row exists (auto-create on first check)
        db_sub_id = _find_db_sub_id(self._db, sub.name)
        if db_sub_id == 0:
            db_sub_id = self._db.save_subscription(
                name=sub.name,
                source_name=sub.source_name,
                match_name=sub.match_name,
                episode_offset=sub.episode_offset,
                enabled=sub.enabled,
            )
        db_sub = self._db.get_subscription(db_sub_id)
        if db_sub:
            last_ep = result.new_episodes[-1] if result.new_episodes else None
            self._db.update_subscription_check(db_sub["id"], last_episode=last_ep)
            for ep in result.new_episodes:
                self._db.add_subscription_event(
                    db_sub["id"], "cart_created", anime_name=default_anime_name, episode=ep,
                    details=f"已创建购物车",
                )
            if not result.new_episodes:
                self._db.add_subscription_event(
                    db_sub["id"], "check_done", anime_name=default_anime_name,
                    details=f"无新剧集（共 {len(items)} 条 RSS）",
                )

        # Also update the config subscription's in-memory last_check_at
        sub.last_check_at = datetime.now().isoformat(timespec="seconds")

        return result


def _candidate_to_cart_dict(candidate: Candidate) -> dict:
    return {
        "title": candidate.title,
        "magnet": candidate.magnet,
        "url": candidate.url,
        "source": candidate.source,
        "seeders": candidate.seeders,
        "score": candidate.score,
        "info_hash": candidate.info_hash,
        "parsed": {
            "group": candidate.group,
            "resolution": candidate.resolution,
            "subtitle_type": candidate.subtitle_type,
            "is_batch": candidate.is_batch,
            "is_raw": candidate.is_raw,
            "episode": candidate.episode,
            "season": candidate.season,
        },
    }


def _find_source(config: AppConfig, name: str):
    if not name:
        return config.rss_sources[0] if config.rss_sources else None
    for s in config.rss_sources:
        if s.name == name:
            return s
    return None


def _find_anime_rule(config: AppConfig, name: str):
    if not name:
        return None
    for rule in config.anime_rules:
        if rule.name == name:
            return rule
    return None


def _find_db_sub_id(db: Database, name: str) -> int:
    for row in db.list_subscriptions():
        if row["name"] == name:
            return row["id"]
    return 0


def _episode_sort_key(episode: str) -> int:
    try:
        return int(episode)
    except ValueError:
        return 0
