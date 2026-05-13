from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from aqsd.models import AnimeRule, Candidate, ExpandedQueryDetail, ScoreBreakdown, ScoreReason, TitleEvidence
from aqsd.scorer import explain_score_candidate, score_candidate


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

    def test_score_reason_and_breakdown_can_be_constructed(self) -> None:
        reason = ScoreReason(code="title_match", delta=25.0, message="title matched: Example Anime")
        breakdown = ScoreBreakdown(total=25.0, reasons=[reason])

        self.assertEqual(breakdown.total, 25.0)
        self.assertEqual(breakdown.reasons[0].code, "title_match")
        self.assertEqual(breakdown.reasons[0].message, "title matched: Example Anime")

    def test_explain_score_candidate_populates_breakdown_and_total_matches_score(self) -> None:
        candidate = Candidate(
            title="[LoliHouse] Example Anime - 01 [1080p][CHS]",
            url="https://example.test/10",
            source="mock",
            group="LoliHouse",
            resolution="1080p",
            subtitle_type="embedded",
            episode="01",
            seeders=12,
            published_at=self.now - timedelta(hours=2),
        )

        score, breakdown = explain_score_candidate(
            candidate,
            self.rule,
            {"prefer": {"resolution": ["1080p"], "subtitle": "embedded"}},
            now=self.now,
            search_context={
                "query": "Example Anime",
                "expanded_queries": ["Example Anime", "Example"],
                "episodes": {"01"},
                "resolution": "1080p",
                "groups": ["LoliHouse"],
                "subtitle_type": "embedded",
                "raw_only": False,
                "min_seeders": 5,
            },
        )

        self.assertIs(candidate.breakdown, breakdown)
        self.assertEqual(candidate.score, score)
        self.assertEqual(candidate.breakdown.total, candidate.score)
        self.assertTrue(candidate.breakdown.reasons)
        self.assertIn("title matched", candidate.score_reasons[0])

    def test_resolved_subject_match_scores_higher_than_weak_alias(self) -> None:
        strong_candidate = Candidate(
            title="Kamiina Botan, Yoeru Sugata wa Yuri no Hana - 01",
            url="https://example.test/strong",
            source="nyaa",
            matched_query="Kamiina Botan, Yoeru Sugata wa Yuri no Hana",
            matched_query_source="bangumi",
            matched_query_confidence=0.93,
            title_evidence=TitleEvidence(
                type="romaji_near_match",
                score=0.93,
                reason="candidate title matched bangumi primary query",
            ),
        )
        weak_candidate = Candidate(
            title="Kamiina Botan, Yoeru Sugata wa Yuri no Hana - 01",
            url="https://example.test/weak",
            source="nyaa",
            matched_query="上伊那牡丹",
            matched_query_source="original",
            matched_query_confidence=0.45,
            title_evidence=TitleEvidence(
                type="zh_near_match",
                score=0.45,
                reason="candidate title matched weak alias",
            ),
        )

        strong_score = score_candidate(
            strong_candidate,
            self.rule,
            {},
            now=self.now,
            search_context={
                "query": "上伊那牡丹，酒醉身姿似百合花般",
                "expanded_query_details": [
                    ExpandedQueryDetail(
                        text="Kamiina Botan, Yoeru Sugata wa Yuri no Hana",
                        source="bangumi",
                        confidence=0.93,
                        language="romaji",
                        search_role="primary",
                    )
                ],
            },
        )
        weak_score = score_candidate(
            weak_candidate,
            self.rule,
            {},
            now=self.now,
            search_context={
                "query": "上伊那牡丹，酒醉身姿似百合花般",
                "expanded_query_details": [
                    ExpandedQueryDetail(
                        text="上伊那牡丹",
                        source="original",
                        confidence=0.45,
                        language="zh",
                        search_role="secondary",
                    )
                ],
            },
        )

        self.assertGreater(strong_score, weak_score)
        self.assertTrue(any("resolved subject" in reason.message for reason in strong_candidate.breakdown.reasons))
        self.assertTrue(any("weak title match" in reason.message for reason in weak_candidate.breakdown.reasons))


if __name__ == "__main__":
    unittest.main()
