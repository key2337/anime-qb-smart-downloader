from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from uuid import uuid4

from aqsd.database import Database
from aqsd.models import DownloadTask


LEGACY_SCHEMA = """
CREATE TABLE download_tasks (
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
"""


class DatabaseTests(unittest.TestCase):
    def _make_db_path(self) -> Path:
        return Path.cwd() / f"test-db-{uuid4().hex}.sqlite3"

    def test_migrates_legacy_download_tasks_table(self) -> None:
        db_path = self._make_db_path()
        try:
            conn = sqlite3.connect(db_path)
            conn.executescript(LEGACY_SCHEMA)
            conn.execute(
                """
                INSERT INTO download_tasks(task_tag, anime_name, episode, title, url, status)
                VALUES ('legacy-task', 'Example Anime', '01', 'legacy title', 'https://example.test/1', 'monitoring')
                """
            )
            conn.commit()
            conn.close()

            db = Database(str(db_path))
            try:
                columns = {
                    row["name"] for row in db.conn.execute("PRAGMA table_info(download_tasks)").fetchall()
                }
                task = db.conn.execute(
                    """
                    SELECT selection_mode, candidate_title, candidate_url, candidate_score, fallback_count, status
                    FROM download_tasks WHERE task_tag = 'legacy-task'
                    """
                ).fetchone()
            finally:
                db.close()

            self.assertIn("selection_mode", columns)
            self.assertIn("candidate_title", columns)
            self.assertIn("candidate_url", columns)
            self.assertIn("candidate_score", columns)
            self.assertIn("fallback_count", columns)
            self.assertEqual(task["selection_mode"], "auto")
            self.assertEqual(task["candidate_title"], "legacy title")
            self.assertEqual(task["candidate_url"], "https://example.test/1")
            self.assertEqual(task["candidate_score"], 0)
            self.assertEqual(task["fallback_count"], 0)
            self.assertEqual(task["status"], "downloading")
        finally:
            db_path.unlink(missing_ok=True)
            wal_path = db_path.with_suffix(db_path.suffix + "-wal")
            shm_path = db_path.with_suffix(db_path.suffix + "-shm")
            wal_path.unlink(missing_ok=True)
            shm_path.unlink(missing_ok=True)

    def test_task_methods_create_update_complete_and_fail(self) -> None:
        db_path = self._make_db_path()
        try:
            db = Database(str(db_path))
            try:
                db.create_download_task(
                    DownloadTask(
                        task_tag="task-1",
                        anime_name="Example Anime",
                        episode="01",
                        title="candidate one",
                        url="https://example.test/1",
                        selection_mode="manual",
                        candidate_score=88.5,
                        source="mock",
                        status="queued",
                    )
                )

                active = db.get_active_tasks()
                self.assertEqual(len(active), 1)
                self.assertEqual(active[0]["selection_mode"], "manual")
                self.assertEqual(active[0]["candidate_title"], "candidate one")
                self.assertEqual(active[0]["candidate_url"], "https://example.test/1")
                self.assertEqual(active[0]["candidate_score"], 88.5)
                self.assertEqual(active[0]["source"], "mock")
                self.assertTrue(db.already_downloaded("Example Anime", "01"))

                db.update_task_status("task-1", "downloading", torrent_hash="hash-1", fallback_count=1)
                updated = db.conn.execute(
                    "SELECT status, torrent_hash, fallback_count FROM download_tasks WHERE task_tag = 'task-1'"
                ).fetchone()
                self.assertEqual(updated["status"], "downloading")
                self.assertEqual(updated["torrent_hash"], "hash-1")
                self.assertEqual(updated["fallback_count"], 1)

                db.mark_task_completed("task-1", torrent_hash="hash-1")
                completed = db.conn.execute(
                    "SELECT status, torrent_hash FROM download_tasks WHERE task_tag = 'task-1'"
                ).fetchone()
                downloaded = db.conn.execute(
                    "SELECT anime_name, episode, title, url FROM downloaded WHERE anime_name = 'Example Anime' AND episode = '01'"
                ).fetchone()
                self.assertEqual(completed["status"], "completed")
                self.assertEqual(downloaded["title"], "candidate one")
                self.assertEqual(downloaded["url"], "https://example.test/1")

                db.create_download_task(
                    DownloadTask(
                        task_tag="task-2",
                        anime_name="Example Anime",
                        episode="02",
                        title="candidate two",
                        url="https://example.test/2",
                        status="submitted",
                    )
                )
                db.mark_task_failed("task-2", "network timeout")
                failed = db.conn.execute(
                    "SELECT status, last_error FROM download_tasks WHERE task_tag = 'task-2'"
                ).fetchone()
                self.assertEqual(failed["status"], "failed")
                self.assertEqual(failed["last_error"], "network timeout")
                self.assertFalse(db.already_downloaded("Example Anime", "02"))
            finally:
                db.close()
        finally:
            db_path.unlink(missing_ok=True)
            wal_path = db_path.with_suffix(db_path.suffix + "-wal")
            shm_path = db_path.with_suffix(db_path.suffix + "-shm")
            wal_path.unlink(missing_ok=True)
            shm_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
