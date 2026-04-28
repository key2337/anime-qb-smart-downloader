from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from aqsd.downloader import add_best_candidates
from aqsd.models import Candidate


class DownloaderTests(unittest.TestCase):
    def test_add_best_candidates_saves_ranked_fallback_pool(self) -> None:
        best = Candidate(
            title="[LoliHouse] Example Anime - 01 [1080p]",
            url="https://example.test/1",
            source="mock",
            anime_name="Example Anime",
            episode="01",
            category="Anime",
            save_path="/downloads/anime",
            score=120.0,
            seeders=10,
        )
        second = Candidate(
            title="[SubsPlease] Example Anime - 01 [1080p]",
            url="https://example.test/2",
            source="mock",
            anime_name="Example Anime",
            episode="01",
            score=100.0,
            seeders=50,
        )
        third_duplicate = Candidate(
            title="[SubsPlease] Example Anime - 01 [1080p] duplicate",
            url="https://example.test/2",
            source="mock",
            anime_name="Example Anime",
            episode="01",
            score=90.0,
            seeders=5,
        )
        qb = MagicMock()
        db = MagicMock()
        db.create_download_task.return_value = 42

        add_best_candidates(qb, db, {("Example Anime", "01"): [second, third_duplicate, best]})

        qb.add_torrent.assert_called_once_with(
            best.url,
            category=best.category,
            save_path=best.save_path,
            tags=best.task_tag,
        )
        db.create_download_task.assert_called_once()
        db.save_fallback_candidates.assert_called_once_with(42, [second, third_duplicate])


if __name__ == "__main__":
    unittest.main()
