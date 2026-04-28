from __future__ import annotations

import unittest

from aqsd.matcher import match_candidate
from aqsd.models import AnimeRule, Candidate


class MatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = [
            AnimeRule(
                name="Example Anime",
                aliases=["示例动画", "Example"],
                profile="preferred_group",
                include=["1080p"],
                reject=["合集"],
                prefer_groups=["LoliHouse"],
                save_path="/downloads/anime/Example Anime",
                category="Anime",
            ),
            AnimeRule(
                name="Raw Show",
                aliases=["RawShow"],
                profile="raw_only",
            ),
        ]
        self.profiles = {
            "preferred_group": {
                "allow_other_group": False,
            },
            "raw_only": {
                "must_include": ["1080p"],
                "reject": ["CHS", "字幕组"],
                "allow_subtitled": False,
            },
        }

    def test_match_by_alias_and_preferred_group(self) -> None:
        candidate = Candidate(
            title="[LoliHouse] 示例动画 - 01 [1080p]",
            url="https://example.test/3",
            source="mikan",
            group="LoliHouse",
            resolution="1080p",
            subtitle_type="unknown",
        )

        matched = match_candidate(candidate, self.rules, self.profiles, "Anime", "/downloads/anime")

        self.assertIsNotNone(matched)
        self.assertEqual(matched.anime_name, "Example Anime")
        self.assertEqual(matched.save_path, "/downloads/anime/Example Anime")

    def test_reject_other_group_when_profile_disallows(self) -> None:
        candidate = Candidate(
            title="[Other] Example Anime - 01 [1080p]",
            url="https://example.test/4",
            source="mikan",
            group="Other",
            resolution="1080p",
            subtitle_type="unknown",
        )

        matched = match_candidate(candidate, self.rules, self.profiles, "Anime", "/downloads/anime")

        self.assertIsNone(matched)

    def test_raw_only_rejects_subtitled_candidate(self) -> None:
        candidate = Candidate(
            title="[DBD] RawShow - 01 [1080p][CHS]",
            url="https://example.test/5",
            source="mikan",
            resolution="1080p",
            subtitle_type="embedded",
        )

        matched = match_candidate(candidate, self.rules, self.profiles, "Anime", "/downloads/anime")

        self.assertIsNone(matched)


if __name__ == "__main__":
    unittest.main()
