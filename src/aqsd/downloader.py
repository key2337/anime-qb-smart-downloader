from __future__ import annotations

from loguru import logger

from aqsd.config import AppConfig
from aqsd.database import Database
from aqsd.discovery import discover_rule_candidates, group_candidates_by_episode
from aqsd.models import Candidate, DownloadTask
from aqsd.qbittorrent import QBittorrentClient
from aqsd.utils import build_task_tag


def collect_candidates(config: AppConfig, db: Database) -> dict[tuple[str, str], list[Candidate]]:
    discovery = discover_rule_candidates(
        config,
        db,
        skip_downloaded=True,
        persist_candidates=True,
    )
    return group_candidates_by_episode(discovery.candidates)


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
