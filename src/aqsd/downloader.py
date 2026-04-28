from __future__ import annotations

from collections import defaultdict

from loguru import logger

from aqsd.config import AppConfig
from aqsd.database import Database
from aqsd.matcher import match_candidate
from aqsd.models import Candidate, DownloadTask
from aqsd.parser import parse_candidate
from aqsd.qbittorrent import QBittorrentClient
from aqsd.rss import fetch_rss
from aqsd.scorer import score_candidate
from aqsd.utils import build_task_tag


def collect_candidates(config: AppConfig, db: Database) -> dict[tuple[str, str], list[Candidate]]:
    rules = config.anime_rules
    rule_by_name = {rule.name: rule for rule in rules}
    default_category = config.qb.default_category
    default_save_path = config.qb.default_save_path

    candidate_pool: dict[tuple[str, str], list[Candidate]] = defaultdict(list)
    seen_urls: set[str] = set()

    for source in config.rss_sources:
        if not source.enabled:
            continue

        logger.info("Fetching RSS: {}", source.name)
        for item in fetch_rss(source):
            if not item.url or item.url in seen_urls:
                continue

            seen_urls.add(item.url)
            candidate = parse_candidate(item)
            matched = match_candidate(
                candidate,
                rules,
                config.profiles,
                default_category,
                default_save_path,
            )
            if not matched or not matched.anime_name or not matched.episode:
                continue

            if db.already_downloaded(matched.anime_name, matched.episode):
                continue

            rule = rule_by_name[matched.matched_rule_name or ""]
            profile = config.profiles.get(rule.profile, {})
            score_candidate(matched, rule, profile)
            db.save_candidate(matched)

            candidate_pool[(matched.anime_name, matched.episode)].append(matched)

    return candidate_pool


def add_best_candidates(qb: QBittorrentClient, db: Database, candidate_pool: dict[tuple[str, str], list[Candidate]]) -> None:
    for (_, _), candidates in candidate_pool.items():
        best = max(candidates, key=lambda item: (item.score, item.seeders))
        best.task_tag = build_task_tag(best.anime_name or "anime", best.episode or "00")

        logger.info("Adding torrent: {} score={}", best.title, best.score)
        qb.add_torrent(
            best.url,
            category=best.category,
            save_path=best.save_path,
            tags=best.task_tag,
        )
        db.record_task(
            DownloadTask(
                task_tag=best.task_tag,
                anime_name=best.anime_name or "unknown",
                episode=best.episode or "00",
                title=best.title,
                url=best.url,
                category=best.category,
                save_path=best.save_path,
            )
        )
        db.mark_downloaded(best)


def run_once(config: AppConfig, db: Database | None = None, qb: QBittorrentClient | None = None) -> None:
    owns_db = db is None
    owns_qb = qb is None
    active_db = db or Database(config.app.database)

    try:
        active_qb = qb or QBittorrentClient(
            base_url=config.qb.base_url,
            username=config.qb.username,
            password=config.qb.password,
        )
        if owns_qb:
            active_qb.login()

        candidate_pool = collect_candidates(config, active_db)
        if not candidate_pool:
            logger.info("No new candidates matched the configured rules.")
            return

        add_best_candidates(active_qb, active_db, candidate_pool)
    finally:
        if owns_db:
            active_db.close()
