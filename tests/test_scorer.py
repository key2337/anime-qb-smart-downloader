from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from aqsd.models import AnimeRule, Candidate
from aqsd.scorer import score_candidate


class ScorerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rule = AnimeRule(
            name="Example Anime",
            prefer_groups=["LoliHouse"],
        )
        self.now = datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc)

    def test_preferred_group_and_resolution_score_higher(self) -> None:
        profile = {
            "prefer": {
                "resolution": ["1080p", "720p"],
                "subtitle": "embedded",
            }
        }
        preferred = Candidate(
            title="preferred",
            url="https://example.test/6",
            source="mikan",
            group="LoliHouse",
            resolution="1080p",
            subtitle_type="embedded",
            seeders=10,
            published_at=self.now - timedelta(hours=1),
        )
        generic = Candidate(
            title="generic",
            url="https://example.test/7",
            source="mikan",
            group="Other",
            resolution="720p",
            subtitle_type="unknown",
            seeders=10,
            published_at=self.now - timedelta(hours=1),
        )

        preferred_score = score_candidate(preferred, self.rule, profile, now=self.now)
        generic_score = score_candidate(generic, self.rule, profile, now=self.now)

        self.assertGreater(preferred_score, generic_score)

    def test_batch_penalty_outweighs_small_seed_bonus(self) -> None:
        profile = {"prefer": ["RAW", "WEB-DL"]}
        normal = Candidate(
            title="normal",
            url="https://example.test/8",
            source="mikan",
            seeders=5,
            is_raw=True,
            source_type="WEB-DL",
        )
        batch = Candidate(
            title="batch",
            url="https://example.test/9",
            source="mikan",
            seeders=6,
            is_raw=True,
            source_type="WEB-DL",
            is_batch=True,
        )

        normal_score = score_candidate(normal, self.rule, profile, now=self.now)
        batch_score = score_candidate(batch, self.rule, profile, now=self.now)

        self.assertGreater(normal_score, batch_score)


if __name__ == "__main__":
    unittest.main()
