from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

from aqsd.config import AppConfig
from aqsd.database import Database
from aqsd.models import DownloadTask
from aqsd.qbittorrent import QBittorrentClient
from aqsd.utils import build_task_tag


@dataclass(slots=True)
class MonitorDecision:
    suspicious: bool
    reasons: list[str]


def evaluate_torrent(
    torrent: dict[str, Any],
    min_download_speed_kbps: int,
    min_progress_delta: float,
    previous_progress: float | None = None,
) -> MonitorDecision:
    reasons: list[str] = []

    speed_kbps = float(torrent.get("dlspeed", 0) or 0) / 1024
    progress = float(torrent.get("progress", 0) or 0)
    seeds = int(torrent.get("num_seeds", 0) or 0)

    if speed_kbps < min_download_speed_kbps:
        reasons.append("low_speed")
    if seeds <= 0:
        reasons.append("no_seeds")
    if previous_progress is not None and progress - previous_progress < min_progress_delta:
        reasons.append("stalled_progress")

    return MonitorDecision(bool(reasons), reasons)


class DownloadMonitor:
    def __init__(self, config: AppConfig, db: Database, qb: QBittorrentClient):
        self.config = config
        self.db = db
        self.qb = qb

    def scan(self) -> None:
        policy = self.config.fallback_policy
        if not policy.enabled:
            return

        torrents = self.qb.list_torrents()
        by_tag: dict[str, dict[str, Any]] = {}
        for torrent in torrents:
            raw_tags = torrent.get("tags", "") or ""
            for tag in [value.strip() for value in raw_tags.split(",") if value.strip()]:
                by_tag[tag] = torrent

        for task in self.db.get_active_tasks():
            task_tag = task["task_tag"]
            torrent = by_tag.get(task_tag)
            if not torrent:
                logger.debug("Task tag {} not visible in qB list yet.", task_tag)
                continue

            progress = float(torrent.get("progress", 0) or 0)
            speed_kbps = float(torrent.get("dlspeed", 0) or 0) / 1024
            torrent_hash = torrent.get("hash")

            if progress >= 1.0:
                self.db.update_task_snapshot(task_tag, torrent_hash, progress, speed_kbps, status="completed")
                self.db.mark_task_completed(task_tag, torrent_hash=torrent_hash)
                self.db.record_task_event(task_tag, "completed", "Download finished.")
                continue

            self.db.update_task_snapshot(task_tag, torrent_hash, progress, speed_kbps)

            decision = evaluate_torrent(
                torrent,
                min_download_speed_kbps=policy.min_download_speed_kbps,
                min_progress_delta=policy.min_progress_delta,
                previous_progress=float(task["last_progress"]),
            )
            if decision.suspicious:
                details = ",".join(decision.reasons)
                self.db.update_task_status(task_tag, "fallback_pending", torrent_hash=torrent_hash)
                self.db.record_task_event(task_tag, "fallback_pending", details)
                logger.warning("Task {} flagged for fallback: {}", task_tag, details)
                self._submit_fallback(task, torrent_hash, details)

    def _submit_fallback(self, task: Any, torrent_hash: str | None, reason: str) -> None:
        task_tag = task["task_tag"]
        fallback = self.db.get_next_fallback_candidate(task["id"])
        if fallback is None:
            error = "no fallback candidates available"
            self.db.update_task_status(task_tag, "failed", torrent_hash=torrent_hash, last_error=error)
            self.db.record_task_event(task_tag, "fallback_failed", error)
            logger.warning("Task {} failed fallback: {}", task_tag, error)
            return

        self.db.mark_fallback_candidate_status(fallback["id"], "used")
        next_fallback_count = int(task["fallback_count"] or 0) + 1
        next_task_tag = build_task_tag(task["anime_name"], task["episode"])

        try:
            self.qb.add_torrent(
                fallback["candidate_url"],
                category=task["category"],
                save_path=task["save_path"],
                tags=next_task_tag,
            )
        except Exception as exc:
            error = f"fallback submit failed: {exc}"
            self.db.mark_fallback_candidate_status(fallback["id"], "failed")
            self.db.update_task_status(task_tag, "fallback_pending", torrent_hash=torrent_hash, last_error=error)
            self.db.record_task_event(task_tag, "fallback_failed", error)
            logger.error("Task {} fallback submit failed: {}", task_tag, exc)
            return

        if self.config.fallback_policy.delete_failed_torrent and torrent_hash:
            try:
                self.qb.delete_torrent(torrent_hash, delete_files=True)
            except Exception as exc:
                logger.warning("Failed to delete old torrent for task {}: {}", task_tag, exc)
                self.db.record_task_event(task_tag, "fallback_delete_failed", str(exc))

        self.db.update_task_status(
            task_tag,
            "fallback_submitted",
            torrent_hash=torrent_hash,
            fallback_count=next_fallback_count,
            last_error=reason,
        )
        self.db.create_download_task(
            DownloadTask(
                task_tag=next_task_tag,
                anime_name=task["anime_name"],
                episode=task["episode"],
                title=fallback["candidate_title"],
                url=fallback["candidate_url"],
                selection_mode=task["selection_mode"],
                candidate_score=float(fallback["candidate_score"] or 0),
                source=fallback["source"],
                category=task["category"],
                save_path=task["save_path"],
                status="submitted",
                fallback_count=next_fallback_count,
            )
        )
        self.db.record_task_event(task_tag, "fallback_submitted", fallback["candidate_url"])
        logger.info("Task {} submitted fallback candidate {}", task_tag, fallback["candidate_url"])
