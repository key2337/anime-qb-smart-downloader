from __future__ import annotations

import sqlite3
from pathlib import Path

from aqsd.models import Candidate, DownloadTask


SCHEMA = """
CREATE TABLE IF NOT EXISTS downloaded (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  anime_name TEXT NOT NULL,
  episode TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(anime_name, episode)
);

CREATE TABLE IF NOT EXISTS candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  anime_name TEXT,
  episode TEXT,
  title TEXT NOT NULL,
  url TEXT NOT NULL UNIQUE,
  score REAL DEFAULT 0,
  source TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS download_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_tag TEXT NOT NULL UNIQUE,
  torrent_hash TEXT,
  anime_name TEXT NOT NULL,
  episode TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  category TEXT,
  save_path TEXT,
  status TEXT NOT NULL DEFAULT 'submitted',
  retry_count INTEGER NOT NULL DEFAULT 0,
  last_progress REAL NOT NULL DEFAULT 0,
  last_speed_kbps REAL NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS task_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_tag TEXT NOT NULL,
  event_type TEXT NOT NULL,
  details TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


ACTIVE_TASK_STATUSES = ("submitted", "monitoring", "fallback_pending")


class Database:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def already_downloaded(self, anime_name: str, episode: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM downloaded WHERE anime_name = ? AND episode = ?",
            (anime_name, episode),
        ).fetchone()
        return row is not None

    def mark_downloaded(self, candidate: Candidate) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO downloaded(anime_name, episode, title, url)
            VALUES (?, ?, ?, ?)
            """,
            (candidate.anime_name, candidate.episode, candidate.title, candidate.url),
        )
        self.conn.commit()

    def save_candidate(self, candidate: Candidate) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO candidates(anime_name, episode, title, url, score, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.anime_name,
                candidate.episode,
                candidate.title,
                candidate.url,
                candidate.score,
                candidate.source,
            ),
        )
        self.conn.commit()

    def record_task(self, task: DownloadTask) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO download_tasks(
                task_tag,
                torrent_hash,
                anime_name,
                episode,
                title,
                url,
                category,
                save_path,
                status,
                retry_count,
                last_progress,
                last_speed_kbps,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                task.task_tag,
                task.torrent_hash,
                task.anime_name,
                task.episode,
                task.title,
                task.url,
                task.category,
                task.save_path,
                task.status,
                task.retry_count,
                task.last_progress,
                task.last_speed_kbps,
            ),
        )
        self.conn.commit()

    def list_active_tasks(self) -> list[sqlite3.Row]:
        placeholders = ", ".join("?" for _ in ACTIVE_TASK_STATUSES)
        rows = self.conn.execute(
            f"SELECT * FROM download_tasks WHERE status IN ({placeholders}) ORDER BY created_at ASC",
            ACTIVE_TASK_STATUSES,
        ).fetchall()
        return list(rows)

    def update_task_snapshot(
        self,
        task_tag: str,
        torrent_hash: str | None,
        progress: float,
        speed_kbps: float,
        status: str = "monitoring",
    ) -> None:
        self.conn.execute(
            """
            UPDATE download_tasks
            SET torrent_hash = ?,
                last_progress = ?,
                last_speed_kbps = ?,
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE task_tag = ?
            """,
            (torrent_hash, progress, speed_kbps, status, task_tag),
        )
        self.conn.commit()

    def mark_task_status(self, task_tag: str, status: str) -> None:
        self.conn.execute(
            """
            UPDATE download_tasks
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE task_tag = ?
            """,
            (status, task_tag),
        )
        self.conn.commit()

    def record_task_event(self, task_tag: str, event_type: str, details: str) -> None:
        self.conn.execute(
            """
            INSERT INTO task_events(task_tag, event_type, details)
            VALUES (?, ?, ?)
            """,
            (task_tag, event_type, details),
        )
        self.conn.commit()
