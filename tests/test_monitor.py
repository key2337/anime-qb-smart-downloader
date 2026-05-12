from __future__ import annotations

import unittest
from pathlib import Path
from uuid import uuid4

from aqsd.config import AppConfig
from aqsd.database import Database
from aqsd.models import Candidate, DownloadTask
from aqsd.monitor import DownloadMonitor


class FakeQBittorrentClient:
    def __init__(self, torrents: list[dict], *, fail_add: bool = False):
        self.torrents = torrents
        self.fail_add = fail_add
        self.added: list[dict] = []
        self.deleted: list[dict] = []

    def list_torrents(self) -> list[dict]:
        return self.torrents

    def add_torrent(
        self,
        url: str,
        category: str | None = None,
        save_path: str | None = None,
        tags: str | None = None,
    ) -> None:
        if self.fail_add:
            raise RuntimeError("qB add failed")
        self.added.append(
            {
                "url": url,
                "category": category,
                "save_path": save_path,
                "tags": tags,
            }
        )

    def delete_torrent(self, torrent_hash: str, delete_files: bool = False) -> None:
        self.deleted.append({"hash": torrent_hash, "delete_files": delete_files})


class MonitorFallbackTests(unittest.TestCase):
    def _make_db_path(self) -> Path:
        return Path.cwd() / f"test-monitor-{uuid4().hex}.sqlite3"

    def _make_config(self, *, delete_failed_torrent: bool = False) -> AppConfig:
        return AppConfig.model_validate(
            {
                "qbittorrent": {
                    "base_url": "http://127.0.0.1:8080",
                    "username": "user",
                    "password": "pass",
                },
                "fallback_policy": {
                    "enabled": True,
                    "min_download_speed_kbps": 100,
                    "min_progress_delta": 0.001,
                    "delete_failed_torrent": delete_failed_torrent,
                },
            }
        )

    def _cleanup_db(self, db_path: Path) -> None:
        db_path.unlink(missing_ok=True)
        db_path.with_suffix(db_path.suffix + "-wal").unlink(missing_ok=True)
        db_path.with_suffix(db_path.suffix + "-shm").unlink(missing_ok=True)

    def _create_task_with_fallback(self, db: Database, *, task_tag: str = "task-1") -> int:
        task_id = db.create_download_task(
            DownloadTask(
                task_tag=task_tag,
                anime_name="Example Anime",
                episode="01",
                title="stalled candidate",
                url="https://example.test/stalled",
                selection_mode="auto",
                candidate_score=100.0,
                source="mock",
                category="Anime",
                save_path="/downloads/anime",
                status="submitted",
            )
        )
        db.save_fallback_candidates(
            task_id,
            [
                Candidate(
                    title="fallback candidate",
                    url="https://example.test/fallback",
                    source="mock",
                    anime_name="Example Anime",
                    episode="01",
                    score=90.0,
                )
            ],
        )
        return task_id

    def _stalled_torrent(self, task_tag: str = "task-1", torrent_hash: str = "hash-1") -> dict:
        return {
            "tags": task_tag,
            "hash": torrent_hash,
            "progress": 0.1,
            "dlspeed": 0,
            "num_seeds": 0,
        }

    def test_submits_next_unused_fallback_candidate(self) -> None:
        db_path = self._make_db_path()
        try:
            db = Database(str(db_path))
            try:
                task_id = self._create_task_with_fallback(db)
                qb = FakeQBittorrentClient([self._stalled_torrent()])

                DownloadMonitor(self._make_config(), db, qb).scan()

                original = db.conn.execute(
                    "SELECT status, fallback_count FROM download_tasks WHERE task_tag = 'task-1'"
                ).fetchone()
                fallback = db.conn.execute(
                    "SELECT status FROM fallback_candidates WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                tasks = db.conn.execute(
                    "SELECT task_tag, title, url, status, selection_mode, fallback_count FROM download_tasks ORDER BY id"
                ).fetchall()

                self.assertEqual(qb.added[0]["url"], "https://example.test/fallback")
                self.assertEqual(qb.added[0]["category"], "Anime")
                self.assertEqual(qb.added[0]["save_path"], "/downloads/anime")
                self.assertEqual(original["status"], "fallback_submitted")
                self.assertEqual(original["fallback_count"], 1)
                self.assertEqual(fallback["status"], "used")
                self.assertEqual(len(tasks), 2)
                self.assertNotEqual(tasks[1]["task_tag"], "task-1")
                self.assertEqual(tasks[1]["title"], "fallback candidate")
                self.assertEqual(tasks[1]["url"], "https://example.test/fallback")
                self.assertEqual(tasks[1]["status"], "submitted")
                self.assertEqual(tasks[1]["selection_mode"], "auto")
                self.assertEqual(tasks[1]["fallback_count"], 1)
            finally:
                db.close()
        finally:
            self._cleanup_db(db_path)

    def test_marks_task_failed_when_no_fallback_candidate_exists(self) -> None:
        db_path = self._make_db_path()
        try:
            db = Database(str(db_path))
            try:
                db.create_download_task(
                    DownloadTask(
                        task_tag="task-1",
                        anime_name="Example Anime",
                        episode="01",
                        title="stalled candidate",
                        url="https://example.test/stalled",
                        status="submitted",
                    )
                )
                qb = FakeQBittorrentClient([self._stalled_torrent()])

                DownloadMonitor(self._make_config(), db, qb).scan()

                task = db.conn.execute(
                    "SELECT status, last_error FROM download_tasks WHERE task_tag = 'task-1'"
                ).fetchone()
                self.assertEqual(task["status"], "failed")
                self.assertEqual(task["last_error"], "no fallback candidates available")
                self.assertEqual(qb.added, [])
            finally:
                db.close()
        finally:
            self._cleanup_db(db_path)

    def test_failed_qb_submit_does_not_create_successful_task(self) -> None:
        db_path = self._make_db_path()
        try:
            db = Database(str(db_path))
            try:
                task_id = self._create_task_with_fallback(db)
                qb = FakeQBittorrentClient([self._stalled_torrent()], fail_add=True)

                DownloadMonitor(self._make_config(), db, qb).scan()

                task = db.conn.execute(
                    "SELECT status, last_error FROM download_tasks WHERE task_tag = 'task-1'"
                ).fetchone()
                fallback = db.conn.execute(
                    "SELECT status FROM fallback_candidates WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                task_count = db.conn.execute("SELECT COUNT(*) AS count FROM download_tasks").fetchone()["count"]

                self.assertEqual(task["status"], "fallback_pending")
                self.assertIn("fallback submit failed", task["last_error"])
                self.assertEqual(fallback["status"], "failed")
                self.assertEqual(task_count, 1)
            finally:
                db.close()
        finally:
            self._cleanup_db(db_path)

    def test_deletes_old_torrent_when_configured(self) -> None:
        db_path = self._make_db_path()
        try:
            db = Database(str(db_path))
            try:
                self._create_task_with_fallback(db)
                qb = FakeQBittorrentClient([self._stalled_torrent(torrent_hash="old-hash")])

                DownloadMonitor(self._make_config(delete_failed_torrent=True), db, qb).scan()

                self.assertEqual(qb.deleted, [{"hash": "old-hash", "delete_files": True}])
            finally:
                db.close()
        finally:
            self._cleanup_db(db_path)

    def test_completed_task_still_writes_downloaded_record(self) -> None:
        db_path = self._make_db_path()
        try:
            db = Database(str(db_path))
            try:
                db.create_download_task(
                    DownloadTask(
                        task_tag="task-1",
                        anime_name="Example Anime",
                        episode="01",
                        title="finished candidate",
                        url="https://example.test/finished",
                        status="submitted",
                    )
                )
                qb = FakeQBittorrentClient(
                    [
                        {
                            "tags": "task-1",
                            "hash": "hash-1",
                            "progress": 1.0,
                            "dlspeed": 0,
                            "num_seeds": 0,
                        }
                    ]
                )

                DownloadMonitor(self._make_config(), db, qb).scan()

                task = db.conn.execute(
                    "SELECT status FROM download_tasks WHERE task_tag = 'task-1'"
                ).fetchone()
                downloaded = db.conn.execute(
                    """
                    SELECT anime_name, episode, title, url
                    FROM downloaded
                    WHERE anime_name = 'Example Anime' AND episode = '01'
                    """
                ).fetchone()
                self.assertEqual(task["status"], "completed")
                self.assertEqual(downloaded["title"], "finished candidate")
                self.assertEqual(downloaded["url"], "https://example.test/finished")
                self.assertEqual(qb.added, [])
            finally:
                db.close()
        finally:
            self._cleanup_db(db_path)


if __name__ == "__main__":
    unittest.main()
