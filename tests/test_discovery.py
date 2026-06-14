from __future__ import annotations

import unittest
from unittest.mock import patch

from aqsd.config import AppConfig
from aqsd.discovery import SearchRequest, discover_rule_candidates, discover_search_candidates
from aqsd.models import Candidate, ExpandedQueryDetail, SearchDiagnostics


class _FakeDatabase:
    def __init__(self, downloaded: set[tuple[str, str]] | None = None) -> None:
        self.downloaded = downloaded or set()
        self.saved_candidates: list[Candidate] = []

    def already_downloaded(self, anime_name: str, episode: str) -> bool:
        return (anime_name, episode) in self.downloaded

    def save_candidate(self, candidate: Candidate) -> None:
        self.saved_candidates.append(candidate)


def _build_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "qbittorrent": {
                "base_url": "http://127.0.0.1:8080",
                "username": "user",
                "password": "pass",
                "default_category": "Anime",
                "default_save_path": "/downloads/anime",
            },
            "rss_sources": [
                {"name": "mock", "url": "https://example.test/rss.xml", "enabled": True},
            ],
            "profiles": {
                "fastest": {
                    "prefer": {
                        "resolution": ["1080p", "720p"],
                        "subtitle": "embedded",
                    }
                }
            },
            "anime": [
                {
                    "name": "Example Anime",
                    "aliases": ["Example"],
                    "profile": "fastest",
                    "prefer_groups": ["LoliHouse"],
                }
            ],
        }
    )


class DiscoveryTests(unittest.TestCase):
    def test_search_diagnostics_can_be_constructed(self) -> None:
        diagnostics = SearchDiagnostics(
            original_query="Angel Beats!",
            expanded_queries=["Angel Beats!"],
            sources=["RSS"],
            active_filters={"episode": "01", "release_mode": "any"},
            candidate_count_before_filter=3,
            candidate_count_after_filter=0,
            suggestions=["可能是集数解析失败，可尝试清空集数后查看候选，或尝试合集 / 整季资源。"],
        )

        self.assertEqual(diagnostics.original_query, "Angel Beats!")
        self.assertEqual(diagnostics.sources, ["RSS"])
        self.assertEqual(diagnostics.active_filters["episode"], "01")

    @patch("aqsd.discovery.fetch_rss")
    def test_discover_rule_candidates_skips_downloaded_and_persists_matches(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[LoliHouse] Example Anime - 01 [WebDL 1080p][CHS]",
                url="https://example.test/1",
                source="mock",
            ),
            Candidate(
                title="[LoliHouse] Example Anime - 02 [WebDL 1080p][CHS]",
                url="https://example.test/2",
                source="mock",
            ),
        ]
        config = _build_config()
        db = _FakeDatabase(downloaded={("Example Anime", "01")})

        result = discover_rule_candidates(
            config,
            db,
            skip_downloaded=True,
            persist_candidates=True,
        )

        self.assertEqual(result.rss_entries_total, 2)
        self.assertEqual(result.parsed_success_total, 2)
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].episode, "02")

    @patch("aqsd.discovery.fetch_rss")
    def test_discover_search_candidates_exclude_batch_filters_batch_results(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[LoliHouse] Example Anime - 01 [1080p][CHS]",
                url="https://example.test/1",
                source="mock",
            ),
            Candidate(
                title="[LoliHouse] Example Anime Batch [1080p][CHS]",
                url="https://example.test/2",
                source="mock",
            ),
        ]

        result = discover_search_candidates(
            _build_config(),
            SearchRequest(query="Example Anime", exclude_batch=True),
        )

        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].episode, "01")
        self.assertEqual(result.diagnostics.active_filters["exclude_batch"], True)

    @patch("aqsd.discovery.fetch_rss")
    def test_discover_search_candidates_release_mode_batch_keeps_batch_results(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[LoliHouse] Example Anime - 01 [1080p][CHS]",
                url="https://example.test/1",
                source="mock",
            ),
            Candidate(
                title="[LoliHouse] Example Anime Batch [1080p][CHS]",
                url="https://example.test/2",
                source="mock",
            ),
        ]

        result = discover_search_candidates(
            _build_config(),
            SearchRequest(query="Example Anime", release_mode="batch"),
        )

        self.assertEqual(len(result.candidates), 1)
        self.assertTrue(result.candidates[0].is_batch)
        self.assertEqual(result.diagnostics.active_filters["release_mode"], "batch")

    @patch("aqsd.discovery.fetch_rss")
    def test_discover_search_candidates_release_mode_batch_allows_episode_filtered_batch_result(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[LoliHouse] Kanon Batch [1080p][CHS]",
                url="https://example.test/kanon-batch",
                source="mock",
            )
        ]

        result = discover_search_candidates(
            _build_config(),
            SearchRequest(query="Kanon", episodes=["21"], release_mode="batch"),
        )

        self.assertEqual(len(result.candidates), 1)
        self.assertTrue(result.candidates[0].is_batch)

    @patch("aqsd.discovery.fetch_rss")
    def test_release_mode_any_without_strong_filters_keeps_multiple_candidates(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(title="[LoliHouse] My Dress-Up Darling - 01 [1080p][CHS]", url="https://example.test/a", source="mock"),
            Candidate(title="[SubsPlease] My Dress-Up Darling - 02 [1080p][CHS]", url="https://example.test/b", source="mock"),
            Candidate(title="[DameDesuYo] My Dress-Up Darling Batch [1080p][CHS]", url="https://example.test/c", source="mock"),
        ]

        result = discover_search_candidates(
            _build_config(),
            SearchRequest(query="My Dress-Up Darling", release_mode="any", limit=20),
        )

        self.assertEqual(len(result.candidates), 3)
        self.assertEqual(result.diagnostics.active_filters, {"release_mode": "any", "limit": 20})
        self.assertEqual(result.diagnostics.stage_counts["count_after_release_mode_filter"], 3)
        self.assertEqual(result.diagnostics.candidate_count_after_filter, 3)

    @patch("aqsd.discovery.fetch_rss")
    def test_without_episode_filter_keeps_null_and_multiple_episode_candidates(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(title="[GroupA] Example Anime [1080p][CHS]", url="https://example.test/no-ep", source="mock"),
            Candidate(title="[GroupB] Example Anime - 01 [1080p][CHS]", url="https://example.test/ep01", source="mock"),
            Candidate(title="[GroupC] Example Anime - 12 [1080p][CHS]", url="https://example.test/ep12", source="mock"),
        ]

        result = discover_search_candidates(_build_config(), SearchRequest(query="Example Anime"))

        self.assertEqual(len(result.candidates), 3)
        self.assertEqual({candidate.episode for candidate in result.candidates}, {None, "01", "12"})

    @patch("aqsd.discovery.fetch_rss")
    def test_dedupe_does_not_merge_candidates_with_different_group_or_episode(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(title="[GroupA] Example Anime - 01 [1080p][CHS]", url="https://example.test/group-a", source="mock"),
            Candidate(title="[GroupB] Example Anime - 01 [1080p][CHS]", url="https://example.test/group-b", source="mock"),
            Candidate(title="[GroupA] Example Anime - 02 [1080p][CHS]", url="https://example.test/group-a-ep2", source="mock"),
        ]

        result = discover_search_candidates(_build_config(), SearchRequest(query="Example Anime"))

        self.assertEqual(len(result.candidates), 3)
        self.assertEqual(result.diagnostics.stage_counts["count_after_dedupe"], 3)
        self.assertEqual(result.diagnostics.filter_drop_reasons.get("duplicate_candidate", 0), 0)

    @patch("aqsd.discovery.fetch_rss")
    def test_limit_applies_after_sorting_not_filtering(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(title="[GroupA] Example Anime - 01 [1080p][CHS]", url="https://example.test/1", source="mock", seeders=1),
            Candidate(title="[GroupB] Example Anime - 02 [1080p][CHS]", url="https://example.test/2", source="mock", seeders=5),
            Candidate(title="[GroupC] Example Anime - 03 [1080p][CHS]", url="https://example.test/3", source="mock", seeders=10),
        ]

        result = discover_search_candidates(_build_config(), SearchRequest(query="Example Anime", limit=2))

        self.assertEqual(len(result.candidates), 2)
        self.assertEqual(result.diagnostics.candidate_count_after_filter, 3)
        self.assertEqual(result.diagnostics.stage_counts["count_after_dedupe"], 3)
        self.assertEqual(result.diagnostics.stage_counts["count_after_limit"], 2)

    @patch("aqsd.discovery.fetch_rss")
    def test_discover_search_candidates_filters_and_scores_results(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[LoliHouse] Example Anime - 01 [WebDL 1080p][CHS]",
                url="https://example.test/1",
                source="mock",
                seeders=12,
            ),
            Candidate(
                title="[Other] Example Anime - 02 [720p][RAW]",
                url="https://example.test/2",
                source="mock",
                seeders=6,
            ),
            Candidate(
                title="[LoliHouse] Another Show - 01 [1080p][CHS]",
                url="https://example.test/3",
                source="mock",
                seeders=30,
            ),
        ]
        config = _build_config()
        request = SearchRequest(
            query="Example Anime",
            subtitle_type="embedded",
            resolution="1080p",
            groups=["LoliHouse"],
        )

        result = discover_search_candidates(config, request)

        self.assertEqual(result.rss_entries_total, 3)
        self.assertEqual(result.parsed_success_total, 3)
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].episode, "01")
        self.assertEqual(result.candidates[0].anime_name, "Example Anime")
        self.assertGreater(result.candidates[0].score, 0.0)
        self.assertIsNotNone(result.candidates[0].breakdown)
        self.assertEqual(result.candidates[0].breakdown.total, result.candidates[0].score)

    @patch("aqsd.discovery.fetch_rss")
    def test_discover_search_candidates_filters_by_episode(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[LoliHouse] Example Anime - 01 [1080p][CHS]",
                url="https://example.test/1",
                source="mock",
            ),
            Candidate(
                title="[LoliHouse] Example Anime - 02 [1080p][CHS]",
                url="https://example.test/2",
                source="mock",
            ),
        ]

        result = discover_search_candidates(
            _build_config(),
            SearchRequest(query="Example Anime", episodes=["02"]),
        )

        self.assertEqual([candidate.episode for candidate in result.candidates], ["02"])

    @patch("aqsd.discovery.fetch_rss")
    def test_discover_search_candidates_filters_by_resolution(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[LoliHouse] Example Anime - 01 [1080p][CHS]",
                url="https://example.test/1",
                source="mock",
            ),
            Candidate(
                title="[LoliHouse] Example Anime - 01 [720p][CHS]",
                url="https://example.test/2",
                source="mock",
            ),
        ]

        result = discover_search_candidates(
            _build_config(),
            SearchRequest(query="Example Anime", resolution="1080p"),
        )

        self.assertEqual([candidate.resolution for candidate in result.candidates], ["1080p"])

    @patch("aqsd.discovery.fetch_rss")
    def test_discover_search_candidates_filters_by_group(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[LoliHouse] Example Anime - 01 [1080p][CHS]",
                url="https://example.test/1",
                source="mock",
            ),
            Candidate(
                title="[Other] Example Anime - 01 [1080p][CHS]",
                url="https://example.test/2",
                source="mock",
            ),
        ]

        result = discover_search_candidates(
            _build_config(),
            SearchRequest(query="Example Anime", groups=["LoliHouse"]),
        )

        self.assertEqual([candidate.group for candidate in result.candidates], ["LoliHouse"])

    @patch("aqsd.discovery.fetch_rss")
    def test_discover_search_candidates_without_requested_groups_does_not_auto_prefer_candidate_group(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[DemiHuman] Example Anime - 01 [1080p][CHS]",
                url="https://example.test/group-auto-prefer",
                source="mock",
            ),
        ]

        result = discover_search_candidates(
            _build_config(),
            SearchRequest(query="Example Anime"),
        )

        self.assertEqual(len(result.candidates), 1)
        reasons = result.candidates[0].breakdown.reasons
        self.assertFalse(any(reason.code == "preferred_group" for reason in reasons))

    @patch("aqsd.discovery.fetch_rss")
    def test_discover_search_candidates_filters_by_subtitle_type(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[LoliHouse] Example Anime - 01 [1080p][CHS]",
                url="https://example.test/1",
                source="mock",
            ),
            Candidate(
                title="[LoliHouse] Example Anime - 01 [1080p][RAW]",
                url="https://example.test/2",
                source="mock",
            ),
        ]

        result = discover_search_candidates(
            _build_config(),
            SearchRequest(query="Example Anime", subtitle_type="embedded"),
        )

        self.assertEqual([candidate.subtitle_type for candidate in result.candidates], ["embedded"])

    @patch("aqsd.discovery.fetch_rss")
    def test_discover_search_candidates_filters_by_raw_only(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[LoliHouse] Example Anime - 01 [1080p][CHS]",
                url="https://example.test/1",
                source="mock",
            ),
            Candidate(
                title="[LoliHouse] Example Anime - 01 [1080p][RAW]",
                url="https://example.test/2",
                source="mock",
            ),
        ]

        result = discover_search_candidates(
            _build_config(),
            SearchRequest(query="Example Anime", raw_only=True),
        )

        self.assertEqual([candidate.is_raw for candidate in result.candidates], [True])

    @patch("aqsd.discovery.fetch_rss")
    def test_discover_search_candidates_applies_min_seeders_and_limit(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[LoliHouse] Example Anime - 01 [1080p][CHS]",
                url="https://example.test/1",
                source="mock",
                seeders=3,
            ),
            Candidate(
                title="[LoliHouse] Example Anime - 02 [1080p][CHS]",
                url="https://example.test/2",
                source="mock",
                seeders=20,
            ),
            Candidate(
                title="[LoliHouse] Example Anime - 03 [1080p][CHS]",
                url="https://example.test/3",
                source="mock",
                seeders=10,
            ),
        ]

        result = discover_search_candidates(
            _build_config(),
            SearchRequest(query="Example Anime", min_seeders=5, limit=1),
        )

        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].episode, "02")

    @patch("aqsd.discovery.fetch_rss")
    def test_search_without_alias_config_keeps_original_behavior(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[SubsPlease] One Punch Man - 01 [1080p][CHS]",
                url="https://example.test/opm-1",
                source="mock",
            )
        ]

        result = discover_search_candidates(_build_config(), SearchRequest(query="一拳超人"))

        # Without title aliases, a Chinese query won't match an English title
        # unless the keyword itself appears in the candidate title
        self.assertEqual(len(result.candidates), 0)

    @patch("aqsd.discovery.fetch_rss")
    def test_search_ignores_release_group_false_positive_for_single_word_query(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[Lain32] Lupin III: The Castle of Cagliostro [480p]",
                url="https://example.test/lupin",
                source="mock",
            ),
            Candidate(
                title="[Chotab] Serial Experiments Lain - 01 [1080p]",
                url="https://example.test/lain",
                source="mock",
            ),
        ]

        result = discover_search_candidates(_build_config(), SearchRequest(query="lain"))

        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].url, "https://example.test/lain")

    @patch("aqsd.discovery.fetch_rss")
    def test_discovery_collects_diagnostics_for_filtered_out_candidates(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[SubsPlease] Example Anime - 01 [720p][CHS]",
                url="https://example.test/1",
                source="mock",
                seeders=8,
            )
        ]

        result = discover_search_candidates(
            _build_config(),
            SearchRequest(query="Example Anime", resolution="1080p", groups=["LoliHouse"], subtitle_type="embedded"),
        )

        self.assertEqual(result.candidates, [])
        self.assertIsNotNone(result.diagnostics)
        self.assertEqual(result.diagnostics.expanded_queries, ["Example Anime"])
        self.assertEqual(result.diagnostics.sources, ["RSS"])
        self.assertEqual(result.diagnostics.candidate_count_before_filter, 1)
        self.assertEqual(result.diagnostics.candidate_count_after_filter, 0)
        self.assertEqual(result.diagnostics.active_filters["resolution"], "1080p")
        self.assertIn("可尝试去掉字幕组限制。", result.diagnostics.suggestions)

    @patch("aqsd.discovery.fetch_rss")
    def test_discovery_diagnostics_suggest_relaxing_episode_filters_when_filtered_out(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[LoliHouse] Kanon Batch [1080p][CHS]",
                url="https://example.test/kanon-batch",
                source="mock",
            )
        ]

        result = discover_search_candidates(
            _build_config(),
            SearchRequest(query="Kanon", episodes=["21"]),
        )

        self.assertEqual(result.candidates, [])
        self.assertIn(
            "可能是集数解析失败，可尝试清空集数后查看候选，或尝试合集 / 整季资源。",
            result.diagnostics.suggestions,
        )

    @patch("aqsd.discovery.fetch_rss")
    def test_discovery_diagnostics_suggest_relaxing_subtitle_filters(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[LoliHouse] Example Anime - 01 [1080p][RAW]",
                url="https://example.test/raw-only",
                source="mock",
            )
        ]

        result = discover_search_candidates(
            _build_config(),
            SearchRequest(query="Example Anime", subtitle_type="embedded"),
        )

        self.assertEqual(result.candidates, [])
        self.assertIn(
            '没有找到符合字幕条件的结果，可尝试改为“不限字幕”。',
            result.diagnostics.suggestions,
        )

    @patch("aqsd.discovery.fetch_rss")
    def test_discovery_keeps_matched_query_evidence_on_candidate(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[SubsPlease] Kamiina Botan, Yoeru Sugata wa Yuri no Hana - 01 [1080p]",
                url="https://example.test/kamiina-1",
                source="mock",
            )
        ]

        request = SearchRequest(
            query="Kamiina Botan, Yoeru Sugata wa Yuri no Hana",
            expanded_query_details=[
                ExpandedQueryDetail(
                    text="Kamiina Botan, Yoeru Sugata wa Yuri no Hana",
                    source="original",
                    confidence=1.0,
                    language="romaji",
                    search_role="primary",
                ),
            ],
            expanded_queries=[
                "Kamiina Botan, Yoeru Sugata wa Yuri no Hana",
            ],
        )

        result = discover_search_candidates(_build_config(), request)

        self.assertEqual(len(result.candidates), 1)
        candidate = result.candidates[0]
        self.assertEqual(candidate.matched_query, "Kamiina Botan, Yoeru Sugata wa Yuri no Hana")
        self.assertEqual(candidate.matched_query_source, "original")
        self.assertIsNotNone(candidate.title_evidence)


if __name__ == "__main__":
    unittest.main()
