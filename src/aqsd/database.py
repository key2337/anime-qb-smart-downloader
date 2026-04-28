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
  selection_mode TEXT NOT NULL DEFAULT 'auto',
  candidate_title TEXT,
  candidate_url TEXT,
  candidate_score REAL NOT NULL DEFAULT 0,
  source TEXT,
  category TEXT,
  save_path TEXT,
  status TEXT NOT NULL DEFAULT 'submitted',
  retry_count INTEGER NOT NULL DEFAULT 0,
  fallback_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
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


ACTIVE_TASK_STATUSES = (
    "queued",
    "submitted",
    "downloading",
    "stalled",
    "fallback_pending",
    "fallback_submitted",
)
EXISTING_TASK_STATUSES = ACTIVE_TASK_STATUSES + ("completed",)
DOWNLOAD_TASK_COLUMNS: dict[str, str] = {
    "selection_mode": "TEXT NOT NULL DEFAULT 'auto'",
    "candidate_title": "TEXT",
    "candidate_url": "TEXT",
    "candidate_score": "REAL NOT NULL DEFAULT 0",
    "source": "TEXT",
    "fallback_count": "INTEGER NOT NULL DEFAULT 0",
    "last_error": "TEXT",
}


class Database:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self._migrate()

    def close(self) -> None:
        self.conn.close()

    def already_downloaded(self, anime_name: str, episode: str) -> bool:
        row = self.conn.execute(
            """
            SELECT 1
            FROM downloaded
            WHERE anime_name = ? AND episode = ?
            UNION
            SELECT 1
            FROM download_tasks
            WHERE anime_name = ? AND episode = ? AND status IN ({})
            LIMIT 1
            """.format(", ".join("?" for _ in EXISTING_TASK_STATUSES)),
            (anime_name, episode, anime_name, episode, *EXISTING_TASK_STATUSES),
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

    def create_download_task(self, task: DownloadTask) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO download_tasks(
                task_tag,
                torrent_hash,
                anime_name,
                episode,
                title,
                url,
                selection_mode,
                candidate_title,
                candidate_url,
                candidate_score,
                source,
                category,
                save_path,
                status,
                retry_count,
                fallback_count,
                last_error,
                last_progress,
                last_speed_kbps,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                task.task_tag,
                task.torrent_hash,
                task.anime_name,
                task.episode,
                task.title,
                task.url,
                task.selection_mode,
                task.title,
                task.url,
                task.candidate_score,
                task.source,
                task.category,
                task.save_path,
                task.status,
                task.retry_count,
                task.fallback_count,
                task.last_error,
                task.last_progress,
                task.last_speed_kbps,
            ),
        )
        self.conn.commit()

    def record_task(self, task: DownloadTask) -> None:
        self.create_download_task(task)

    def get_active_tasks(self) -> list[sqlite3.Row]:
        placeholders = ", ".join("?" for _ in ACTIVE_TASK_STATUSES)
        rows = self.conn.execute(
            f"SELECT * FROM download_tasks WHERE status IN ({placeholders}) ORDER BY created_at ASC",
            ACTIVE_TASK_STATUSES,
        ).fetchall()
        return list(rows)

    def list_active_tasks(self) -> list[sqlite3.Row]:
        return self.get_active_tasks()

    def update_task_snapshot(
        self,
        task_tag: str,
        torrent_hash: str | None,
        progress: float,
        speed_kbps: float,
        status: str = "downloading",
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

    def update_task_status(
        self,
        task_tag: str,
        status: str,
        *,
        torrent_hash: str | None = None,
        last_error: str | None = None,
        fallback_count: int | None = None,
    ) -> None:
        current = self.conn.execute(
            "SELECT torrent_hash, fallback_count, last_error FROM download_tasks WHERE task_tag = ?",
            (task_tag,),
        ).fetchone()
        if current is None:
            return

        next_torrent_hash = torrent_hash if torrent_hash is not None else current["torrent_hash"]
        next_last_error = last_error if last_error is not None else current["last_error"]
        next_fallback_count = fallback_count if fallback_count is not None else current["fallback_count"]
        self.conn.execute(
            """
            UPDATE download_tasks
            SET status = ?,
                torrent_hash = ?,
                fallback_count = ?,
                last_error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE task_tag = ?
            """,
            (status, next_torrent_hash, next_fallback_count, next_last_error, task_tag),
        )
        self.conn.commit()

    def mark_task_status(self, task_tag: str, status: str) -> None:
        self.update_task_status(task_tag, status)

    def mark_task_completed(self, task_tag: str, torrent_hash: str | None = None) -> None:
        task = self.conn.execute(
            "SELECT anime_name, episode, candidate_title, candidate_url FROM download_tasks WHERE task_tag = ?",
            (task_tag,),
        ).fetchone()
        if task is None:
            return

        self.update_task_status(task_tag, "completed", torrent_hash=torrent_hash, last_error=None)
        self.conn.execute(
            """
            INSERT OR IGNORE INTO downloaded(anime_name, episode, title, url)
            VALUES (?, ?, ?, ?)
            """,
            (task["anime_name"], task["episode"], task["candidate_title"] or "", task["candidate_url"] or ""),
        )
        self.conn.commit()

    def mark_task_failed(self, task_tag: str, error: str) -> None:
        self.update_task_status(task_tag, "failed", last_error=error)

    def record_task_event(self, task_tag: str, event_type: str, details: str) -> None:
        self.conn.execute(
            """
            INSERT INTO task_events(task_tag, event_type, details)
            VALUES (?, ?, ?)
            """,
            (task_tag, event_type, details),
        )
        self.conn.commit()

    def _migrate(self) -> None:
        existing_columns = {
            row["name"] for row in self.conn.execute("PRAGMA table_info(download_tasks)").fetchall()
        }
        for name, definition in DOWNLOAD_TASK_COLUMNS.items():
            if name in existing_columns:
                continue
            self.conn.execute(f"ALTER TABLE download_tasks ADD COLUMN {name} {definition}")

        self.conn.execute(
            """
            UPDATE download_tasks
            SET candidate_title = COALESCE(candidate_title, title),
                candidate_url = COALESCE(candidate_url, url),
                selection_mode = COALESCE(selection_mode, 'auto'),
                candidate_score = COALESCE(candidate_score, 0),
                fallback_count = COALESCE(fallback_count, 0)
            """
        )
        self.conn.execute("UPDATE download_tasks SET status = 'downloading' WHERE status = 'monitoring'")
        self.conn.commit()
