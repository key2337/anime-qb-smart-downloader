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

    def test_parse_dmhy_bracket_episode(self) -> None:
        candidate = Candidate(
            title="[Skymoon-Raws][One Piece 海賊王][1165][ViuTV][WEB-RIP][CHT][SRT][1080p][MKV]",
            url="https://example.test/3",
            source="dmhy",
        )
        parsed = parse_candidate(candidate)
        self.assertEqual(parsed.group, "Skymoon-Raws")
        self.assertEqual(parsed.episode, "1165")
        self.assertEqual(parsed.resolution, "1080p")
        self.assertEqual(parsed.source_type, "WEBRip")
        self.assertTrue(parsed.is_raw)

    def test_parse_dmhy_free_text_episode(self) -> None:
        candidate = Candidate(
            title="[ANi] ONE PIECE / 航海王 - 1168 [1080P][Baha][WEB-DL][AAC AVC][CHT][MP4]",
            url="https://example.test/4",
            source="dmhy",
        )
        parsed = parse_candidate(candidate)
        self.assertEqual(parsed.group, "ANi")
        self.assertEqual(parsed.episode, "1168")
        self.assertEqual(parsed.resolution, "1080p")

    def test_parse_dmhy_chinese_season(self) -> None:
        candidate = Candidate(
            title="[NC-Raws] 我的幸福婚约 第二季 / Watashi S2 - 09 [1080p][WEB-DL][CHT]",
            url="https://example.test/5",
            source="dmhy",
        )
        parsed = parse_candidate(candidate)
        self.assertEqual(parsed.episode, "09")
        self.assertEqual(parsed.season, 2)

    def test_parse_dmhy_season_bracket(self) -> None:
        candidate = Candidate(
            title="[桜都字幕组] 实力至上主义教室 S4 [13][WebRip][1080p][簡繁內封]",
            url="https://example.test/6",
            source="dmhy",
        )
        parsed = parse_candidate(candidate)
        self.assertEqual(parsed.episode, "13")
        self.assertEqual(parsed.season, 4)
        self.assertEqual(parsed.subtitle_type, "embedded")

    def test_parse_dmhy_batch_and_multi_episode(self) -> None:
        candidate = Candidate(
            title="[DBD-Raws] 龍珠大魔 / Dragon Ball Daima - 01-20 合集 [BDRip 1080p HEVC-10bit FLAC][簡繁外掛]",
            url="https://example.test/7",
            source="dmhy",
        )
        parsed = parse_candidate(candidate)
        self.assertEqual(parsed.episode, "01")
        self.assertTrue(parsed.is_batch)
        self.assertEqual(parsed.subtitle_type, "external")

    def test_parse_dmhy_end_marker_as_batch(self) -> None:
        candidate = Candidate(
            title="[jibaketa合成][代理商粵語]葬送的芙莉蓮 S2 - 10 END [字幕]",
            url="https://example.test/8",
            source="dmhy",
        )
        parsed = parse_candidate(candidate)
        self.assertEqual(parsed.episode, "10")
        self.assertTrue(parsed.is_batch)

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
