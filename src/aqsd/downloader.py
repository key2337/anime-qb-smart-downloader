from __future__ import annotations

from loguru import logger

from aqsd.config import AppConfig
from aqsd.database import Database
from aqsd.discovery import discover_rule_candidates, group_candidates_by_episode
from aqsd.models import Candidate, DownloadTask
from aqsd.qbittorrent import QBittorrentClient
from aqsd.utils import build_task_tag, fix_magnet_name


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
        ranked_candidates = sorted(candidates, key=lambda item: (item.score, item.seeders, item.title), reverse=True)
        best = ranked_candidates[0]
        best.task_tag = build_task_tag(best.anime_name or "anime", best.episode or "00")

        download_url = fix_magnet_name(best.magnet or best.url, best.title)
        logger.info("Adding torrent: {} score={}", best.title, best.score)
        qb.add_torrent(
            download_url,
            category=best.category,
            save_path=best.save_path,
            tags=best.task_tag,
        )
        task_id = db.create_download_task(
            DownloadTask(
                task_tag=best.task_tag,
                anime_name=best.anime_name or "unknown",
                episode=best.episode or "00",
                title=best.title,
                url=best.url,
                selection_mode="auto",
                candidate_score=best.score,
                source=best.source,
                category=best.category,
                save_path=best.save_path,
            )
        )
        db.save_fallback_candidates(task_id, ranked_candidates[1:])
        # TODO: submission to qB is not completion. Future fallback logic should
        # rely on task status transitions instead of treating this as downloaded.


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
