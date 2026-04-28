from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

from aqsd.config import AppConfig
from aqsd.database import Database
from aqsd.qbittorrent import QBittorrentClient


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

        for task in self.db.list_active_tasks():
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
                self.db.mark_task_status(task_tag, "fallback_pending")
                self.db.record_task_event(task_tag, "fallback_pending", details)
                logger.warning("Task {} flagged for fallback: {}", task_tag, details)
