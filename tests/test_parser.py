from __future__ import annotations

import unittest

from aqsd.models import Candidate
from aqsd.parser import parse_candidate


class ParserTests(unittest.TestCase):
    def test_parse_standard_release_title(self) -> None:
        candidate = Candidate(
            title="[LoliHouse] Example Anime - 01 [WebDL 1080p][CHS]",
            url="https://example.test/1",
            source="mikan",
        )

        parsed = parse_candidate(candidate)

        self.assertEqual(parsed.group, "LoliHouse")
        self.assertEqual(parsed.episode, "01")
        self.assertEqual(parsed.resolution, "1080p")
        self.assertEqual(parsed.source_type, "WEB-DL")
        self.assertEqual(parsed.subtitle_type, "embedded")
        self.assertTrue(parsed.is_raw)

    def test_parse_batch_and_revision_release(self) -> None:
        candidate = Candidate(
            title="[NC-Raws] Example Anime 第12集 v2 [1080p][外挂字幕][合集]",
            url="https://example.test/2",
            source="mikan",
        )

        parsed = parse_candidate(candidate)

        self.assertEqual(parsed.episode, "12")
        self.assertTrue(parsed.is_v2)
        self.assertTrue(parsed.is_batch)
        self.assertEqual(parsed.subtitle_type, "external")


if __name__ == "__main__":
    unittest.main()
