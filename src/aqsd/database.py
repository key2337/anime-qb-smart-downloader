from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
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

CREATE TABLE IF NOT EXISTS fallback_candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  anime_name TEXT NOT NULL,
  episode TEXT NOT NULL,
  candidate_title TEXT NOT NULL,
  candidate_url TEXT NOT NULL,
  candidate_score REAL NOT NULL DEFAULT 0,
  source TEXT,
  rank INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'unused',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(task_id, candidate_url)
);

CREATE TABLE IF NOT EXISTS title_metadata_cache (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  query TEXT NOT NULL,
  aliases_json TEXT NOT NULL,
  source TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  expires_at TIMESTAMP NOT NULL,
  UNIQUE(query, source)
);

CREATE TABLE IF NOT EXISTS subscriptions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  enabled INTEGER NOT NULL DEFAULT 1,
  source_name TEXT NOT NULL DEFAULT '',
  match_name TEXT NOT NULL DEFAULT '',
  episode_offset INTEGER NOT NULL DEFAULT 0,
  last_check_at TIMESTAMP,
  last_episode TEXT
);

CREATE TABLE IF NOT EXISTS subscription_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  subscription_id INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  anime_name TEXT NOT NULL DEFAULT '',
  episode TEXT,
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
        self.conn = sqlite3.connect(path, check_same_thread=False)
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

    def create_download_task(self, task: DownloadTask) -> int:
        cursor = self.conn.execute(
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
        return int(cursor.lastrowid)

    def record_task(self, task: DownloadTask) -> int:
        return self.create_download_task(task)

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

    def save_fallback_candidates(self, task_id: int, candidates: list[Candidate]) -> None:
        existing_urls = {
            row["candidate_url"]
            for row in self.conn.execute(
                "SELECT candidate_url FROM fallback_candidates WHERE task_id = ?",
                (task_id,),
            ).fetchall()
        }
        current_max_rank = self.conn.execute(
            "SELECT COALESCE(MAX(rank), 0) AS max_rank FROM fallback_candidates WHERE task_id = ?",
            (task_id,),
        ).fetchone()["max_rank"]
        ranked_candidates = sorted(candidates, key=lambda item: (item.score, item.seeders, item.title), reverse=True)

        next_rank = int(current_max_rank)
        for candidate in ranked_candidates:
            if candidate.url in existing_urls:
                continue
            next_rank += 1
            self.conn.execute(
                """
                INSERT OR IGNORE INTO fallback_candidates(
                    task_id,
                    anime_name,
                    episode,
                    candidate_title,
                    candidate_url,
                    candidate_score,
                    source,
                    rank,
                    status,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'unused', CURRENT_TIMESTAMP)
                """,
                (
                    task_id,
                    candidate.anime_name or "unknown",
                    candidate.episode or "00",
                    candidate.title,
                    candidate.magnet or candidate.url,
                    candidate.score,
                    candidate.source,
                    next_rank,
                ),
            )
            existing_urls.add(candidate.url)
        self.conn.commit()

    def get_next_fallback_candidate(self, task_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT *
            FROM fallback_candidates
            WHERE task_id = ? AND status = 'unused'
            ORDER BY rank ASC, id ASC
            LIMIT 1
            """,
            (task_id,),
        ).fetchone()

    def mark_fallback_candidate_status(self, candidate_id: int, status: str) -> None:
        self.conn.execute(
            """
            UPDATE fallback_candidates
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, candidate_id),
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

    def get_title_metadata_cache(self, query: str, source: str):
        now = datetime.now(timezone.utc)
        self.conn.execute(
            "DELETE FROM title_metadata_cache WHERE expires_at <= ?",
            (now.isoformat(),),
        )
        self.conn.commit()
        row = self.conn.execute(
            """
            SELECT aliases_json, expires_at
            FROM title_metadata_cache
            WHERE query = ? AND source = ?
            """,
            (query, source),
        ).fetchone()
        if row is None:
            return None

        expires_at = _parse_cache_datetime(row["expires_at"])
        if expires_at is None or expires_at <= now:
            return None

        try:
            payload = json.loads(row["aliases_json"])
        except json.JSONDecodeError:
            return None
        return payload

    def get_title_alias_cache(self, query: str, source: str) -> list[str] | None:
        payload = self.get_title_metadata_cache(query, source)
        if not isinstance(payload, list):
            return None
        return [str(alias) for alias in payload if str(alias).strip()]

    def save_title_alias_cache(self, query: str, aliases: list[str], source: str, ttl_days: int) -> None:
        self.save_title_metadata_cache(query, aliases, source, ttl_days)

    def save_title_metadata_cache(self, query: str, payload, source: str, ttl_days: int) -> None:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=ttl_days)
        self.conn.execute(
            """
            INSERT OR REPLACE INTO title_metadata_cache(query, aliases_json, source, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                query,
                json.dumps(payload, ensure_ascii=False),
                source,
                now.isoformat(),
                expires_at.isoformat(),
            ),
        )
        self.conn.commit()

    def delete_title_alias_cache(self, query: str, source: str) -> None:
        self.conn.execute(
            """
            DELETE FROM title_metadata_cache
            WHERE query = ? AND source = ?
            """,
            (query, source),
        )
        self.conn.commit()

    # ── subscriptions ────────────────────────────────────

    def list_subscriptions(self) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM subscriptions ORDER BY id ASC"
        ).fetchall())

    def get_subscription(self, sub_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM subscriptions WHERE id = ?", (sub_id,)
        ).fetchone()

    def save_subscription(self, name: str, source_name: str = "", match_name: str = "",
                          episode_offset: int = 0, enabled: bool = True) -> int:
        cursor = self.conn.execute(
            """
            INSERT OR REPLACE INTO subscriptions(name, enabled, source_name, match_name, episode_offset)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, int(enabled), source_name, match_name, episode_offset),
        )
        self.conn.commit()
        return cursor.lastrowid or 0

    def update_subscription_check(self, sub_id: int, last_episode: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if last_episode is not None:
            self.conn.execute(
                "UPDATE subscriptions SET last_check_at = ?, last_episode = ? WHERE id = ?",
                (now, last_episode, sub_id),
            )
        else:
            self.conn.execute(
                "UPDATE subscriptions SET last_check_at = ? WHERE id = ?",
                (now, sub_id),
            )
        self.conn.commit()

    def delete_subscription(self, sub_id: int) -> bool:
        cursor = self.conn.execute("DELETE FROM subscriptions WHERE id = ?", (sub_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def add_subscription_event(self, sub_id: int, event_type: str, anime_name: str = "",
                               episode: str | None = None, details: str = "") -> None:
        self.conn.execute(
            """
            INSERT INTO subscription_events(subscription_id, event_type, anime_name, episode, details)
            VALUES (?, ?, ?, ?, ?)
            """,
            (sub_id, event_type, anime_name, episode, details),
        )
        self.conn.commit()

    def get_recent_events(self, limit: int = 100) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            """
            SELECT e.*, s.name as subscription_name
            FROM subscription_events e
            LEFT JOIN subscriptions s ON s.id = e.subscription_id
            ORDER BY e.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall())

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


def _parse_cache_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
