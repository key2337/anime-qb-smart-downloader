from __future__ import annotations

import unittest
from unittest.mock import patch

from aqsd.config import AppConfig
from aqsd.discovery import SearchRequest, discover_rule_candidates, discover_search_candidates
from aqsd.models import Candidate, ExpandedQueryDetail, SearchDiagnostics
from aqsd.anilist import TitleMetadata
from aqsd.title_resolver import TitleResolution


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


def _build_alias_config() -> AppConfig:
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
            "title_aliases": [
                {
                    "canonical": "一拳超人",
                    "aliases": [
                        "一拳超人",
                        "一击男",
                        "One Punch Man",
                        "One-Punch Man",
                        "Wanpanman",
                        "ワンパンマン",
                    ],
                }
            ],
        }
    )


def _build_nyaa_config() -> AppConfig:
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
            "search_sources": {
                "nyaa": {
                    "enabled": True,
                    "base_url": "https://nyaa.si",
                    "default_category": "1_2",
                    "timeout_seconds": 15,
                }
            },
            "title_aliases": [
                {
                    "canonical": "一拳超人",
                    "aliases": [
                        "一拳超人",
                        "One Punch Man",
                        "One-Punch Man",
                        "ワンパンマン",
                    ],
                }
            ],
        }
    )


def _build_all_search_sources_config() -> AppConfig:
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
            "search_sources": {
                "nyaa": {
                    "enabled": True,
                    "base_url": "https://nyaa.si",
                    "default_category": "1_2",
                    "timeout_seconds": 15,
                },
                "torznab": {
                    "enabled": True,
                    "endpoints": [
                        {
                            "name": "jackett-nyaa",
                            "url": "http://127.0.0.1:9117/api/v2.0/indexers/nyaa/results/torznab/",
                            "api_key": "secret",
                            "categories": [],
                            "timeout_seconds": 15,
                        },
                        {
                            "name": "prowlarr-other",
                            "url": "http://127.0.0.1:9696/1/api",
                            "api_key": "secret",
                            "categories": ["5070"],
                            "timeout_seconds": 15,
                        },
                    ],
                },
            },
            "title_aliases": [
                {
                    "canonical": "OPM",
                    "aliases": ["OPM", "One Punch Man", "One-Punch Man"],
                }
            ],
        }
    )


def _build_anilist_search_config() -> AppConfig:
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
            "search_sources": {
                "nyaa": {
                    "enabled": True,
                    "base_url": "https://nyaa.si",
                    "default_category": "1_2",
                    "timeout_seconds": 15,
                },
                "torznab": {
                    "enabled": True,
                    "endpoints": [
                        {
                            "name": "jackett-nyaa",
                            "url": "http://127.0.0.1:9117/api/v2.0/indexers/nyaa/results/torznab/",
                            "api_key": "secret",
                            "categories": [],
                            "timeout_seconds": 15,
                        }
                    ],
                },
            },
            "metadata_sources": {
                "anilist": {
                    "enabled": True,
                    "endpoint": "https://graphql.anilist.co",
                    "timeout_seconds": 15,
                    "cache_enabled": False,
                    "cache_ttl_days": 30,
                }
            },
        }
    )


def _build_bangumi_search_config() -> AppConfig:
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
            "metadata_sources": {
                "bangumi": {
                    "enabled": True,
                    "timeout_seconds": 8,
                    "max_results": 5,
                },
                "anilist": {
                    "enabled": False,
                },
            },
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

    @patch("aqsd.discovery.resolve_search_title")
    @patch("aqsd.discovery.fetch_rss")
    def test_diagnostics_resolution_status_is_normalized_when_subject_missing(self, mock_fetch_rss, mock_resolve_search_title) -> None:
        mock_fetch_rss.return_value = []
        mock_resolve_search_title.return_value = TitleResolution(
            canonical="Example Anime",
            expanded_queries=["Example Anime"],
            expanded_query_details=[ExpandedQueryDetail(text="Example Anime", source="original")],
            resolution_status="resolved_medium_confidence",
            resolved_subject=None,
        )

        result = discover_search_candidates(_build_config(), SearchRequest(query="Example Anime"))

        self.assertEqual(result.diagnostics.resolution_status, "unresolved")
        self.assertIsNone(result.diagnostics.resolved_subject)

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
    def test_chinese_query_matches_english_title_alias(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[SubsPlease] One Punch Man - 01 [1080p][CHS]",
                url="https://example.test/opm-1",
                source="mock",
            )
        ]

        result = discover_search_candidates(_build_alias_config(), SearchRequest(query="一拳超人"))

        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].title, "[SubsPlease] One Punch Man - 01 [1080p][CHS]")

    @patch("aqsd.discovery.fetch_rss")
    def test_english_query_matches_canonical_alias_group(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[SubsPlease] ワンパンマン - 01 [1080p][CHS]",
                url="https://example.test/opm-jp-1",
                source="mock",
            )
        ]

        result = discover_search_candidates(_build_alias_config(), SearchRequest(query="One Punch Man"))

        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].title, "[SubsPlease] ワンパンマン - 01 [1080p][CHS]")

    @patch("aqsd.discovery.fetch_rss")
    def test_hyphenated_english_query_matches_space_title(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[SubsPlease] One Punch Man - 01 [1080p][CHS]",
                url="https://example.test/opm-1",
                source="mock",
            )
        ]

        result = discover_search_candidates(_build_alias_config(), SearchRequest(query="One-Punch Man"))

        self.assertEqual(len(result.candidates), 1)

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

        self.assertEqual(result.candidates, [])

    @patch("aqsd.discovery.fetch_nyaa_candidates")
    @patch("aqsd.discovery.fetch_rss")
    def test_search_merges_rss_and_nyaa_results(self, mock_fetch_rss, mock_fetch_nyaa_candidates) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[RSS] Example Anime - 01 [1080p][CHS]",
                url="https://example.test/rss-1",
                source="mock",
                seeders=5,
            )
        ]
        mock_fetch_nyaa_candidates.return_value = [
            Candidate(
                title="[Nyaa] Example Anime - 02 [1080p][CHS]",
                url="https://nyaa.si/view/2",
                source="nyaa",
                seeders=20,
            )
        ]

        result = discover_search_candidates(_build_nyaa_config(), SearchRequest(query="Example Anime"))

        self.assertEqual({candidate.url for candidate in result.candidates}, {"https://example.test/rss-1", "https://nyaa.si/view/2"})
        mock_fetch_nyaa_candidates.assert_called()

    @patch("aqsd.discovery.fetch_nyaa_candidates")
    @patch("aqsd.discovery.fetch_rss")
    def test_title_alias_expanded_queries_are_used_for_nyaa_search(
        self,
        mock_fetch_rss,
        mock_fetch_nyaa_candidates,
    ) -> None:
        mock_fetch_rss.return_value = []
        mock_fetch_nyaa_candidates.return_value = []

        discover_search_candidates(_build_nyaa_config(), SearchRequest(query="一拳超人"))

        called_queries = [call.args[1] for call in mock_fetch_nyaa_candidates.call_args_list]
        self.assertIn("一拳超人", called_queries)
        self.assertIn("One Punch Man", called_queries)
        self.assertIn("One-Punch Man", called_queries)
        self.assertIn("ワンパンマン", called_queries)

    @patch("aqsd.discovery.fetch_nyaa_candidates")
    @patch("aqsd.discovery.fetch_rss")
    def test_duplicate_candidates_are_deduplicated_across_rss_and_nyaa(
        self,
        mock_fetch_rss,
        mock_fetch_nyaa_candidates,
    ) -> None:
        title = "[SubsPlease] Example Anime - 01 [1080p][CHS]"
        mock_fetch_rss.return_value = [
            Candidate(title=title, url="https://example.test/rss-1", source="mock", seeders=5)
        ]
        mock_fetch_nyaa_candidates.return_value = [
            Candidate(title=title, url="https://nyaa.si/view/duplicate", source="nyaa", seeders=20)
        ]

        result = discover_search_candidates(_build_nyaa_config(), SearchRequest(query="Example Anime"))

        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].url, "https://example.test/rss-1")

    @patch("aqsd.discovery.fetch_nyaa_candidates")
    @patch("aqsd.discovery.fetch_rss")
    def test_nyaa_failure_does_not_block_rss_results(self, mock_fetch_rss, mock_fetch_nyaa_candidates) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[RSS] Example Anime - 01 [1080p][CHS]",
                url="https://example.test/rss-1",
                source="mock",
                seeders=5,
            )
        ]
        mock_fetch_nyaa_candidates.side_effect = RuntimeError("network unavailable")

        result = discover_search_candidates(_build_nyaa_config(), SearchRequest(query="Example Anime"))

        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].url, "https://example.test/rss-1")

    @patch("aqsd.discovery.fetch_torznab_candidates")
    @patch("aqsd.discovery.fetch_nyaa_candidates")
    @patch("aqsd.discovery.fetch_rss")
    def test_search_merges_rss_nyaa_and_torznab_results(
        self,
        mock_fetch_rss,
        mock_fetch_nyaa_candidates,
        mock_fetch_torznab_candidates,
    ) -> None:
        mock_fetch_rss.return_value = [
            Candidate(title="[RSS] Example Anime - 01 [1080p]", url="https://example.test/rss-1", source="mock")
        ]
        mock_fetch_nyaa_candidates.return_value = [
            Candidate(title="[Nyaa] Example Anime - 02 [1080p]", url="https://nyaa.si/view/2", source="nyaa")
        ]
        mock_fetch_torznab_candidates.return_value = [
            Candidate(title="[Torznab] Example Anime - 03 [1080p]", url="magnet:?xt=urn:btih:torznab03", source="jackett")
        ]

        result = discover_search_candidates(_build_all_search_sources_config(), SearchRequest(query="Example Anime"))

        self.assertEqual(
            {candidate.url for candidate in result.candidates},
            {"https://example.test/rss-1", "https://nyaa.si/view/2", "magnet:?xt=urn:btih:torznab03"},
        )

    @patch("aqsd.discovery.fetch_torznab_candidates")
    @patch("aqsd.discovery.fetch_nyaa_candidates")
    @patch("aqsd.discovery.fetch_rss")
    def test_title_alias_expanded_queries_are_used_for_torznab_search(
        self,
        mock_fetch_rss,
        mock_fetch_nyaa_candidates,
        mock_fetch_torznab_candidates,
    ) -> None:
        mock_fetch_rss.return_value = []
        mock_fetch_nyaa_candidates.return_value = []
        mock_fetch_torznab_candidates.return_value = []

        discover_search_candidates(_build_all_search_sources_config(), SearchRequest(query="OPM"))

        called_queries = [call.args[1] for call in mock_fetch_torznab_candidates.call_args_list]
        self.assertIn("OPM", called_queries)
        self.assertIn("One Punch Man", called_queries)
        self.assertIn("One-Punch Man", called_queries)

    @patch("aqsd.discovery.fetch_torznab_candidates")
    @patch("aqsd.discovery.fetch_nyaa_candidates")
    @patch("aqsd.discovery.fetch_rss")
    def test_torznab_endpoint_failure_does_not_block_other_sources(
        self,
        mock_fetch_rss,
        mock_fetch_nyaa_candidates,
        mock_fetch_torznab_candidates,
    ) -> None:
        mock_fetch_rss.return_value = [
            Candidate(title="[RSS] Example Anime - 01 [1080p]", url="https://example.test/rss-1", source="mock")
        ]
        mock_fetch_nyaa_candidates.return_value = []
        mock_fetch_torznab_candidates.side_effect = [
            RuntimeError("endpoint down"),
            [Candidate(title="[Torznab] Example Anime - 02 [1080p]", url="magnet:?xt=urn:btih:torznab02", source="prowlarr")],
        ]

        config = _build_all_search_sources_config()
        config.search_sources.nyaa.enabled = False
        result = discover_search_candidates(config, SearchRequest(query="Example Anime"))

        self.assertEqual(
            {candidate.url for candidate in result.candidates},
            {"https://example.test/rss-1", "magnet:?xt=urn:btih:torznab02"},
        )

    @patch("aqsd.discovery.fetch_torznab_candidates")
    @patch("aqsd.discovery.fetch_nyaa_candidates")
    @patch("aqsd.discovery.fetch_rss")
    def test_torznab_hash_deduplication_keeps_first_candidate(
        self,
        mock_fetch_rss,
        mock_fetch_nyaa_candidates,
        mock_fetch_torznab_candidates,
    ) -> None:
        mock_fetch_rss.return_value = []
        mock_fetch_nyaa_candidates.return_value = []
        mock_fetch_torznab_candidates.side_effect = [
            [
                Candidate(
                    title="[First] Example Anime - 01 [1080p]",
                    url="magnet:?xt=urn:btih:SAMEHASH",
                    source="jackett",
                    info_hash="SAMEHASH",
                )
            ],
            [
                Candidate(
                    title="[Second] Example Anime - 01 [1080p]",
                    url="https://example.test/download/same",
                    source="prowlarr",
                    info_hash="samehash",
                )
            ],
        ]

        config = _build_all_search_sources_config()
        config.search_sources.nyaa.enabled = False
        result = discover_search_candidates(config, SearchRequest(query="Example Anime"))

        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].url, "magnet:?xt=urn:btih:SAMEHASH")

    @patch("aqsd.title_resolver.fetch_anilist_title_metadata")
    @patch("aqsd.discovery.fetch_rss")
    def test_discovery_search_uses_anilist_expanded_queries_for_rss_matching(
        self,
        mock_fetch_rss,
        mock_fetch_anilist,
    ) -> None:
        mock_fetch_anilist.return_value = [
            TitleMetadata(canonical="One Punch Man", aliases=["One Punch Man", "ワンパンマン"])
        ]
        mock_fetch_rss.return_value = [
            Candidate(
                title="[SubsPlease] One Punch Man - 01 [1080p][CHS]",
                url="https://example.test/opm-1",
                source="mock",
            )
        ]
        config = _build_anilist_search_config()
        config.search_sources.nyaa.enabled = False
        config.search_sources.torznab.enabled = False

        result = discover_search_candidates(config, SearchRequest(query="一拳超人"))

        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].title, "[SubsPlease] One Punch Man - 01 [1080p][CHS]")

    @patch("aqsd.title_resolver.fetch_anilist_title_metadata")
    @patch("aqsd.discovery.fetch_torznab_candidates")
    @patch("aqsd.discovery.fetch_nyaa_candidates")
    @patch("aqsd.discovery.fetch_rss")
    def test_anilist_expanded_queries_are_used_for_nyaa_and_torznab_search(
        self,
        mock_fetch_rss,
        mock_fetch_nyaa_candidates,
        mock_fetch_torznab_candidates,
        mock_fetch_anilist,
    ) -> None:
        mock_fetch_rss.return_value = []
        mock_fetch_nyaa_candidates.return_value = []
        mock_fetch_torznab_candidates.return_value = []
        mock_fetch_anilist.return_value = [
            TitleMetadata(
                canonical="One Punch Man",
                aliases=["One Punch Man", "One-Punch Man", "ワンパンマン"],
                romaji="One Punch Man",
                english="One-Punch Man",
                native="ワンパンマン",
            )
        ]

        discover_search_candidates(_build_anilist_search_config(), SearchRequest(query="一拳超人"))

        nyaa_queries = [call.args[1] for call in mock_fetch_nyaa_candidates.call_args_list]
        torznab_queries = [call.args[1] for call in mock_fetch_torznab_candidates.call_args_list]
        self.assertIn("一拳超人", nyaa_queries)
        self.assertIn("One Punch Man", nyaa_queries)
        self.assertIn("ワンパンマン", nyaa_queries)
        self.assertIn("一拳超人", torznab_queries)
        self.assertIn("One Punch Man", torznab_queries)
        self.assertIn("ワンパンマン", torznab_queries)


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
    def test_short_alias_does_not_match_unrelated_longer_token(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[Gecko] AOTU WORLD REBORN - S01E04 [1080p]",
                url="https://example.test/aotu",
                source="mock",
            ),
            Candidate(
                title="[Judas] Attack on Titan - 01 [1080p]",
                url="https://example.test/aot",
                source="mock",
            ),
        ]
        config = _build_all_search_sources_config()
        config.search_sources.nyaa.enabled = False
        config.search_sources.torznab.enabled = False
        config = AppConfig.model_validate(
            {
                **config.model_dump(),
                "title_aliases": [
                    {
                        "canonical": "Attack on Titan",
                        "aliases": ["Attack on Titan", "Shingeki no Kyojin", "AoT"],
                    }
                ],
            }
        )

        result = discover_search_candidates(config, SearchRequest(query="Attack on Titan"))

        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].url, "https://example.test/aot")

    @patch("aqsd.title_resolver.fetch_anilist_title_metadata")
    @patch("aqsd.discovery.fetch_torznab_candidates")
    @patch("aqsd.discovery.fetch_nyaa_candidates")
    @patch("aqsd.discovery.fetch_rss")
    def test_discovery_uses_anilist_expanded_queries_for_nyaa_search(
        self,
        mock_fetch_rss,
        mock_fetch_nyaa_candidates,
        mock_fetch_torznab_candidates,
        mock_fetch_anilist,
    ) -> None:
        mock_fetch_rss.return_value = []
        mock_fetch_nyaa_candidates.return_value = []
        mock_fetch_torznab_candidates.return_value = []
        mock_fetch_anilist.return_value = [
            TitleMetadata(
                canonical="Angel Beats!",
                aliases=["Angel Beats!", "エンジェルビーツ", "天使的心跳"],
                romaji="Angel Beats!",
                english="Angel Beats!",
                native="エンジェルビーツ",
            )
        ]

        discover_search_candidates(_build_anilist_search_config(), SearchRequest(query="天使的心跳"))

        called_queries = [call.args[1] for call in mock_fetch_nyaa_candidates.call_args_list]
        self.assertIn("天使的心跳", called_queries)
        self.assertIn("Angel Beats!", called_queries)
        self.assertIn("エンジェルビーツ", called_queries)

    @patch("aqsd.title_resolver.fetch_anilist_title_metadata")
    @patch("aqsd.discovery.fetch_torznab_candidates")
    @patch("aqsd.discovery.fetch_nyaa_candidates")
    @patch("aqsd.discovery.fetch_rss")
    def test_discovery_uses_anilist_expanded_queries_for_torznab_search(
        self,
        mock_fetch_rss,
        mock_fetch_nyaa_candidates,
        mock_fetch_torznab_candidates,
        mock_fetch_anilist,
    ) -> None:
        mock_fetch_rss.return_value = []
        mock_fetch_nyaa_candidates.return_value = []
        mock_fetch_torznab_candidates.return_value = []
        mock_fetch_anilist.return_value = [
            TitleMetadata(
                canonical="Angel Beats!",
                aliases=["Angel Beats!", "エンジェルビーツ", "天使的心跳"],
                romaji="Angel Beats!",
                english="Angel Beats!",
                native="エンジェルビーツ",
            )
        ]

        discover_search_candidates(_build_anilist_search_config(), SearchRequest(query="天使的心跳"))

        called_queries = [call.args[1] for call in mock_fetch_torznab_candidates.call_args_list]
        self.assertIn("天使的心跳", called_queries)
        self.assertIn("Angel Beats!", called_queries)
        self.assertIn("エンジェルビーツ", called_queries)


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
    def test_discovery_diagnostics_suggest_enabling_active_search_sources(self, mock_fetch_rss) -> None:
        mock_fetch_rss.return_value = []

        result = discover_search_candidates(_build_config(), SearchRequest(query="Example Anime"))

        self.assertEqual(result.candidates, [])
        self.assertIsNotNone(result.diagnostics)
        self.assertIn("RSS", result.diagnostics.sources)
        self.assertIn("可检查 config.yaml 的 search_sources，按需启用 Nyaa 或 Torznab。", result.diagnostics.suggestions)

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
            "没有找到符合字幕条件的结果，可尝试改为“不限字幕”。",
            result.diagnostics.suggestions,
        )

    @patch("aqsd.title_resolver.search_bangumi_titles")
    @patch("aqsd.discovery.fetch_rss")
    def test_discovery_search_uses_bangumi_expanded_queries_for_rss_matching(
        self,
        mock_fetch_rss,
        mock_search_bangumi,
    ) -> None:
        from aqsd.bangumi import BangumiTitleMetadata

        mock_search_bangumi.return_value = [
            BangumiTitleMetadata(
                subject_id=1,
                name="Angel Beats!",
                name_cn="天使的心跳",
                aliases=["Angel Beats!", "天使的心跳", "エンジェルビーツ"],
            )
        ]
        mock_fetch_rss.return_value = [
            Candidate(
                title="[SubsPlease] Angel Beats! - 01 [1080p][CHS]",
                url="https://example.test/ab-1",
                source="mock",
            )
        ]

        result = discover_search_candidates(_build_bangumi_search_config(), SearchRequest(query="天使的心跳"))

        self.assertEqual(len(result.candidates), 1)
        self.assertIn("Angel Beats!", result.diagnostics.expanded_queries)

    @patch("aqsd.discovery.fetch_torznab_candidates")
    @patch("aqsd.discovery.fetch_nyaa_candidates")
    @patch("aqsd.discovery.fetch_rss")
    def test_discovery_only_searches_eligible_queries_from_selected_bangumi_subject(
        self,
        mock_fetch_rss,
        mock_fetch_nyaa_candidates,
        mock_fetch_torznab_candidates,
    ) -> None:
        mock_fetch_rss.return_value = []
        mock_fetch_nyaa_candidates.return_value = []
        mock_fetch_torznab_candidates.return_value = []
        request = SearchRequest(
            query="上伊那牡丹，酒醉身姿似百合花般",
            expanded_queries=[
                "上伊那牡丹，酒醉身姿似百合花般",
                "上伊那ぼたん、酔へる姿は百合の花",
                "上伊那牡丹，醉姿如百合",
                "Kamiina Botan, Yoeru Sugata wa Yuri no Hana",
                "Kamiina Botan, the Drunken Appearance Is a Lily Flower",
            ],
            expanded_query_details=[
                ExpandedQueryDetail(text="上伊那牡丹，酒醉身姿似百合花般", source="original", confidence=0.6, language="zh", search_role="secondary"),
                ExpandedQueryDetail(text="上伊那ぼたん、酔へる姿は百合の花", source="bangumi", confidence=0.94, language="ja", subject_id=101, search_role="primary"),
                ExpandedQueryDetail(text="上伊那牡丹，醉姿如百合", source="bangumi", confidence=0.94, language="zh", subject_id=101, search_role="primary"),
                ExpandedQueryDetail(text="Kamiina Botan, Yoeru Sugata wa Yuri no Hana", source="bangumi", confidence=0.94, language="romaji", subject_id=101, search_role="primary"),
                ExpandedQueryDetail(text="Kamiina Botan, the Drunken Appearance Is a Lily Flower", source="bangumi", confidence=0.82, language="en", subject_id=101, search_role="primary"),
                ExpandedQueryDetail(text="The Upper Classman", source="bangumi", confidence=0.20, language="en", subject_id=102, search_role="display_only", search_eligible=False),
                ExpandedQueryDetail(text="Joukyuusei", source="bangumi", confidence=0.20, language="romaji", subject_id=102, search_role="display_only", search_eligible=False),
                ExpandedQueryDetail(text="崖上的波妞", source="bangumi", confidence=0.20, language="zh", subject_id=103, search_role="display_only", search_eligible=False),
            ],
        )

        discover_search_candidates(_build_all_search_sources_config(), request)

        nyaa_queries = [call.args[1] for call in mock_fetch_nyaa_candidates.call_args_list]
        torznab_queries = [call.args[1] for call in mock_fetch_torznab_candidates.call_args_list]
        self.assertIn("上伊那ぼたん、酔へる姿は百合の花", nyaa_queries)
        self.assertIn("Kamiina Botan, Yoeru Sugata wa Yuri no Hana", nyaa_queries)
        self.assertNotIn("上級生", nyaa_queries)
        self.assertNotIn("The Upper Classman", nyaa_queries)
        self.assertNotIn("Joukyuusei", nyaa_queries)
        self.assertNotIn("崖の上のポニョ", torznab_queries)
        self.assertNotIn("崖上的波妞", torznab_queries)

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
            query="上伊那牡丹，酒醉身姿似百合花般",
            expanded_query_details=[
                ExpandedQueryDetail(
                    text="上伊那牡丹，酒醉身姿似百合花般",
                    source="original",
                    confidence=0.6,
                    language="zh",
                    search_role="secondary",
                ),
                ExpandedQueryDetail(
                    text="Kamiina Botan, Yoeru Sugata wa Yuri no Hana",
                    source="bangumi",
                    confidence=0.93,
                    subject_id=101,
                    language="romaji",
                    search_role="primary",
                ),
            ],
            expanded_queries=[
                "上伊那牡丹，酒醉身姿似百合花般",
                "Kamiina Botan, Yoeru Sugata wa Yuri no Hana",
            ],
        )

        result = discover_search_candidates(_build_config(), request)

        self.assertEqual(len(result.candidates), 1)
        candidate = result.candidates[0]
        self.assertEqual(candidate.matched_query, "Kamiina Botan, Yoeru Sugata wa Yuri no Hana")
        self.assertEqual(candidate.matched_query_source, "bangumi")
        self.assertEqual(candidate.matched_query_subject_id, 101)
        self.assertIsNotNone(candidate.title_evidence)


if __name__ == "__main__":
    unittest.main()
