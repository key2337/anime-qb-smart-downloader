from __future__ import annotations

import unittest

from aqsd.config import ProbePolicy
from aqsd.models import Candidate
from aqsd.probe import probe_candidates


class FakeQBittorrentClient:
    def __init__(self, stats_by_url: dict[str, dict] | None = None, *, fail_add: bool = False):
        self.stats_by_url = stats_by_url or {}
        self.fail_add = fail_add
        self.added: list[dict] = []
        self.deleted: list[dict] = []
        self.list_calls = 0

    def add_torrent(
        self,
        url: str,
        category: str | None = None,
        save_path: str | None = None,
        tags: str | None = None,
        paused: bool = False,
    ) -> None:
        if self.fail_add:
            raise RuntimeError("add failed")
        self.added.append({"url": url, "category": category, "save_path": save_path, "tags": tags, "paused": paused})

    def list_torrents(self) -> list[dict]:
        self.list_calls += 1
        torrents = []
        for index, item in enumerate(self.added, start=1):
            stats = self.stats_by_url.get(item["url"], {})
            if self.list_calls == 1:
                stats = {**stats, "progress": stats.get("initial_progress", 0)}
            torrents.append(
                {
                    "tags": item["tags"],
                    "hash": f"hash-{index}",
                    "progress": stats.get("progress", 0),
                    "dlspeed": stats.get("dlspeed", 0),
                    "num_seeds": stats.get("num_seeds", 0),
                    "num_leechs": stats.get("num_leechs", 0),
                    "availability": stats.get("availability", 0),
                }
            )
        return torrents

    def delete_torrent(self, torrent_hash: str, delete_files: bool = False) -> None:
        self.deleted.append({"hash": torrent_hash, "delete_files": delete_files})

    def pause_torrents(self, hashes: str) -> None:
        pass

    def resume_torrents(self, hashes: str) -> None:
        pass


def _candidate(title: str, url: str, *, score: float = 100.0, seeders: int = 0) -> Candidate:
    return Candidate(
        title=title,
        url=url,
        source="mock",
        anime_name="Example Anime",
        episode="01",
        score=score,
        seeders=seeders,
        category="Anime",
        save_path="/downloads/anime",
    )


class ProbeTests(unittest.TestCase):
    def _policy(self, *, delete_losers: bool = True) -> ProbePolicy:
        return ProbePolicy(
            enabled=True,
            max_candidates=3,
            duration_seconds=0,
            min_speed_kbps=50,
            delete_losers=delete_losers,
        )

    def test_selects_candidate_with_higher_real_qb_speed(self) -> None:
        slow = _candidate("high score slow", "https://example.test/slow", score=120)
        fast = _candidate("lower score fast", "https://example.test/fast", score=80)
        qb = FakeQBittorrentClient(
            {
                slow.url: {"dlspeed": 20 * 1024, "num_seeds": 1, "availability": 1.0},
                fast.url: {"dlspeed": 300 * 1024, "num_seeds": 1, "availability": 1.0},
            }
        )

        result = probe_candidates([slow, fast], qb, self._policy(), sleep_fn=lambda _: None)

        self.assertIs(result.selected, fast)

    def test_rss_seeders_do_not_win_when_qb_has_no_connections(self) -> None:
        stale = _candidate("rss says many seeds", "https://example.test/stale", score=120, seeders=999)
        active = _candidate("real qB activity", "https://example.test/active", score=80, seeders=1)
        qb = FakeQBittorrentClient(
            {
                stale.url: {"dlspeed": 0, "num_seeds": 0, "num_leechs": 0, "availability": 0},
                active.url: {"dlspeed": 80 * 1024, "num_seeds": 1, "num_leechs": 2, "availability": 1.0},
            }
        )

        result = probe_candidates([stale, active], qb, self._policy(), sleep_fn=lambda _: None)

        self.assertIs(result.selected, active)

    def test_deletes_loser_candidates_when_enabled(self) -> None:
        winner = _candidate("winner", "https://example.test/winner")
        loser = _candidate("loser", "https://example.test/loser")
        qb = FakeQBittorrentClient(
            {
                winner.url: {"dlspeed": 200 * 1024, "num_seeds": 2},
                loser.url: {"dlspeed": 0, "num_seeds": 0},
            }
        )

        result = probe_candidates([winner, loser], qb, self._policy(delete_losers=True), sleep_fn=lambda _: None)

        self.assertIs(result.selected, winner)
        self.assertEqual(qb.deleted, [{"hash": "hash-2", "delete_files": True}])

    def test_returns_none_when_all_probe_adds_fail(self) -> None:
        candidates = [
            _candidate("candidate one", "https://example.test/1"),
            _candidate("candidate two", "https://example.test/2"),
        ]
        qb = FakeQBittorrentClient(fail_add=True)

        result = probe_candidates(candidates, qb, self._policy(), sleep_fn=lambda _: None)

        self.assertIsNone(result.selected)
        self.assertEqual(result.attempts, [])


if __name__ == "__main__":
    unittest.main()
