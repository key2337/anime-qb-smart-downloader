from __future__ import annotations

import unittest
from dataclasses import dataclass
from unittest.mock import patch

from aqsd.anilist import TitleMetadata
from aqsd.bangumi import BangumiTitleMetadata
from aqsd.title_resolver import (
    ANILIST_CACHE_SOURCE,
    BANGUMI_CACHE_SOURCE,
    contains_cjk,
    resolve_title_query,
)


@dataclass(slots=True)
class _AliasGroup:
    canonical: str
    aliases: list[str]


@dataclass(slots=True)
class _AniListSettings:
    enabled: bool = True
    endpoint: str = "https://graphql.anilist.co"
    timeout_seconds: int = 15
    cache_enabled: bool = True
    cache_ttl_days: int = 30


@dataclass(slots=True)
class _BangumiSettings:
    enabled: bool = True
    timeout_seconds: int = 8
    max_results: int = 5


class _FakeCache:
    def __init__(
        self,
        aliases_by_source: dict[str, list[str]] | None = None,
        metadata_by_source: dict[str, object] | None = None,
    ) -> None:
        self.aliases_by_source = aliases_by_source or {}
        self.metadata_by_source = metadata_by_source or {}
        self.saved: tuple[str, list[str], str, int] | None = None
        self.saved_metadata: tuple[str, object, str, int] | None = None
        self.deleted: tuple[str, str] | None = None

    def get_title_alias_cache(self, query: str, source: str) -> list[str] | None:
        return self.aliases_by_source.get(source)

    def save_title_alias_cache(self, query: str, aliases: list[str], source: str, ttl_days: int) -> None:
        self.saved = (query, aliases, source, ttl_days)

    def delete_title_alias_cache(self, query: str, source: str) -> None:
        self.deleted = (query, source)

    def get_title_metadata_cache(self, query: str, source: str):
        return self.metadata_by_source.get(source)

    def save_title_metadata_cache(self, query: str, payload: object, source: str, ttl_days: int) -> None:
        self.saved_metadata = (query, payload, source, ttl_days)


class TitleResolverTests(unittest.TestCase):
    def test_contains_cjk_detects_chinese_and_japanese(self) -> None:
        self.assertTrue(contains_cjk("天使的心跳"))
        self.assertTrue(contains_cjk("エンジェルビーツ"))
        self.assertFalse(contains_cjk("Angel Beats"))

    @patch("aqsd.title_resolver.fetch_anilist_title_metadata")
    @patch("aqsd.title_resolver.search_bangumi_titles")
    def test_local_title_aliases_take_priority_over_external_sources(self, mock_search_bangumi, mock_fetch_anilist) -> None:
        result = resolve_title_query(
            "天使的心跳",
            [_AliasGroup(canonical="Angel Beats!", aliases=["天使的心跳", "Angel Beats!"])],
            bangumi_settings=_BangumiSettings(enabled=True),
            anilist_settings=_AniListSettings(enabled=True),
        )

        self.assertEqual(result.source, "local")
        self.assertEqual(result.sources, ["local_aliases"])
        self.assertTrue(result.local_alias_matched)
        self.assertEqual(result.expanded_queries, ["Angel Beats!", "天使的心跳"])
        mock_search_bangumi.assert_not_called()
        mock_fetch_anilist.assert_not_called()

    @patch("aqsd.title_resolver.search_bangumi_titles")
    def test_chinese_query_uses_bangumi_expansion_when_enabled(self, mock_search_bangumi) -> None:
        mock_search_bangumi.return_value = [
            BangumiTitleMetadata(
                subject_id=1,
                name="Angel Beats!",
                name_cn="天使的心跳",
                aliases=["Angel Beats!", "天使的心跳", "エンジェルビーツ"],
            )
        ]
        cache = _FakeCache()

        result = resolve_title_query(
            "天使的心跳",
            [],
            bangumi_settings=_BangumiSettings(enabled=True),
            anilist_settings=_AniListSettings(enabled=False),
            cache=cache,
        )

        self.assertEqual(result.source, "bangumi")
        self.assertIn("bangumi", result.sources)
        self.assertTrue(result.bangumi_enabled)
        self.assertTrue(result.bangumi_attempted)
        self.assertEqual(result.canonical, "Angel Beats!")
        self.assertEqual(result.expanded_queries[0], "天使的心跳")
        self.assertIn("Angel Beats!", result.expanded_queries)
        self.assertIn("エンジェルビーツ", result.expanded_queries)
        self.assertIsNotNone(cache.saved_metadata)
        self.assertEqual(cache.saved_metadata[2], BANGUMI_CACHE_SOURCE)

    @patch("aqsd.title_resolver.fetch_anilist_title_metadata")
    @patch("aqsd.title_resolver.search_bangumi_titles")
    def test_bangumi_failure_falls_back_to_anilist(self, mock_search_bangumi, mock_fetch_anilist) -> None:
        mock_search_bangumi.return_value = []
        mock_fetch_anilist.return_value = [
            TitleMetadata(
                canonical="Angel Beats!",
                aliases=["Angel Beats!", "エンジェルビーツ", "天使的心跳"],
                romaji="Angel Beats!",
                english="Angel Beats!",
                native="エンジェルビーツ",
                year=2010,
            )
        ]

        result = resolve_title_query(
            "天使的心跳",
            [],
            bangumi_settings=_BangumiSettings(enabled=True),
            anilist_settings=_AniListSettings(enabled=True, cache_enabled=False),
        )

        self.assertEqual(result.source, "anilist")
        self.assertTrue(result.bangumi_attempted)
        self.assertTrue(result.anilist_attempted)
        self.assertIn("Angel Beats!", result.expanded_queries)
        self.assertEqual(result.expanded_queries[0], "天使的心跳")

    @patch("aqsd.title_resolver.search_bangumi_titles")
    def test_original_query_is_always_preserved_in_expanded_queries(self, mock_search_bangumi) -> None:
        mock_search_bangumi.return_value = [
            BangumiTitleMetadata(
                subject_id=2,
                name="Kanon",
                name_cn="雪之少女",
                aliases=["Kanon", "カノン"],
            )
        ]

        result = resolve_title_query(
            "雪之少女",
            [],
            bangumi_settings=_BangumiSettings(enabled=True),
            anilist_settings=_AniListSettings(enabled=False),
        )

        self.assertIn("雪之少女", result.expanded_queries)
        self.assertEqual(result.expanded_queries[0], "雪之少女")

    @patch("aqsd.title_resolver.search_bangumi_titles")
    def test_bangumi_cache_hit_skips_network_request(self, mock_search_bangumi) -> None:
        cached_payload = {
            "schema_version": 2,
            "query": "天使的心跳",
            "source": "bangumi",
            "created_at": "2026-05-13T00:00:00+00:00",
            "resolved_subject": {
                "source": "bangumi",
                "subject_id": 1,
                "canonical": "Angel Beats!",
                "confidence": 0.93,
                "reason": "best_name_cn_similarity=0.980",
            },
            "expanded_query_details": [
                {
                    "text": "天使的心跳",
                    "source": "original",
                    "confidence": 1.0,
                    "language": "zh",
                    "alias_confidence": 1.0,
                    "search_eligible": True,
                    "search_tier": "secondary",
                },
                {
                    "text": "Angel Beats!",
                    "source": "bangumi",
                    "confidence": 0.91,
                    "language": "en",
                    "subject_id": 1,
                    "subject_confidence": 0.93,
                    "alias_confidence": 0.91,
                    "search_eligible": True,
                    "search_tier": "primary",
                },
                {
                    "text": "エンジェルビーツ",
                    "source": "bangumi",
                    "confidence": 0.86,
                    "language": "ja",
                    "subject_id": 1,
                    "subject_confidence": 0.93,
                    "alias_confidence": 0.86,
                    "search_eligible": True,
                    "search_tier": "primary",
                },
                {
                    "text": "AB!",
                    "source": "bangumi",
                    "confidence": 0.2,
                    "language": "en",
                    "subject_id": 1,
                    "subject_confidence": 0.93,
                    "alias_confidence": 0.2,
                    "search_eligible": False,
                    "search_tier": "display_only",
                },
            ],
            "rejected_subjects": [],
        }
        result = resolve_title_query(
            "天使的心跳",
            [],
            bangumi_settings=_BangumiSettings(enabled=True),
            anilist_settings=_AniListSettings(enabled=False),
            cache=_FakeCache(metadata_by_source={BANGUMI_CACHE_SOURCE: cached_payload}),
        )

        self.assertEqual(result.source, "bangumi-cache")
        self.assertTrue(result.cache_hit)
        self.assertIn("bangumi", result.sources)
        self.assertIn("cache", result.sources)
        self.assertEqual(result.expanded_queries, ["天使的心跳", "Angel Beats!", "エンジェルビーツ"])
        self.assertEqual(result.expanded_query_details[1].confidence, 0.91)
        mock_search_bangumi.assert_not_called()

    @patch("aqsd.title_resolver.fetch_anilist_title_metadata")
    def test_incomplete_anilist_cache_does_not_block_valid_anilist_expansion(self, mock_fetch_anilist) -> None:
        mock_fetch_anilist.return_value = [
            TitleMetadata(
                canonical="Angel Beats!",
                aliases=["Angel Beats!", "エンジェルビーツ", "天使的心跳"],
                romaji="Angel Beats!",
                english="Angel Beats!",
                native="エンジェルビーツ",
            )
        ]
        cache = _FakeCache({ANILIST_CACHE_SOURCE: ["天使的心跳"]})

        result = resolve_title_query(
            "天使的心跳",
            [],
            bangumi_settings=_BangumiSettings(enabled=False),
            anilist_settings=_AniListSettings(enabled=True),
            cache=cache,
        )

        self.assertEqual(result.source, "anilist")
        self.assertIn("Angel Beats!", result.expanded_queries)
        self.assertEqual(cache.deleted, ("天使的心跳", ANILIST_CACHE_SOURCE))
        mock_fetch_anilist.assert_called_once()

    @patch("aqsd.title_resolver.fetch_anilist_title_metadata")
    def test_disabled_anilist_and_bangumi_do_not_request_metadata(self, mock_fetch_anilist) -> None:
        result = resolve_title_query(
            "天使的心跳",
            [],
            bangumi_settings=_BangumiSettings(enabled=False),
            anilist_settings=_AniListSettings(enabled=False),
        )

        self.assertEqual(result.source, "query")
        self.assertFalse(result.bangumi_attempted)
        self.assertFalse(result.anilist_attempted)
        self.assertEqual(result.expanded_queries, ["天使的心跳"])
        mock_fetch_anilist.assert_not_called()

    @patch("aqsd.title_resolver.search_bangumi_titles")
    def test_bangumi_only_uses_selected_subject_aliases(self, mock_search_bangumi) -> None:
        mock_search_bangumi.return_value = [
            BangumiTitleMetadata(
                subject_id=101,
                name="上伊那ぼたん、酔へる姿は百合の花",
                name_cn="上伊那牡丹，醉姿如百合",
                aliases=[
                    "上伊那ぼたん、酔へる姿は百合の花",
                    "上伊那牡丹，醉姿如百合",
                    "Kamiina Botan, Yoeru Sugata wa Yuri no Hana",
                    "Kamiina Botan, the Drunken Appearance Is a Lily Flower",
                ],
            ),
            BangumiTitleMetadata(
                subject_id=102,
                name="上級生",
                name_cn="The Upper Classman",
                aliases=["上級生", "The Upper Classman", "Joukyuusei"],
            ),
            BangumiTitleMetadata(
                subject_id=103,
                name="みんなのうた",
                name_cn="Minna no Uta",
                aliases=["Minna no Uta", "上前线"],
            ),
            BangumiTitleMetadata(
                subject_id=104,
                name="崖の上のポニョ",
                name_cn="崖上的波妞",
                aliases=["崖の上のポニョ", "崖上的波妞"],
            ),
        ]

        result = resolve_title_query(
            "上伊那牡丹，酒醉身姿似百合花般",
            [],
            bangumi_settings=_BangumiSettings(enabled=True),
            anilist_settings=_AniListSettings(enabled=False),
        )

        self.assertEqual(result.source, "bangumi")
        self.assertIn("上伊那ぼたん、酔へる姿は百合の花", result.expanded_queries)
        self.assertIn("上伊那牡丹，醉姿如百合", result.expanded_queries)
        self.assertIn("Kamiina Botan, Yoeru Sugata wa Yuri no Hana", result.expanded_queries)
        self.assertIn("Kamiina Botan, the Drunken Appearance Is a Lily Flower", result.expanded_queries)
        self.assertNotIn("上級生", result.expanded_queries)
        self.assertNotIn("The Upper Classman", result.expanded_queries)
        self.assertNotIn("Minna no Uta", result.expanded_queries)
        self.assertNotIn("Joukyuusei", result.expanded_queries)
        self.assertNotIn("上前线", result.expanded_queries)
        self.assertNotIn("崖の上のポニョ", result.expanded_queries)
        self.assertNotIn("崖上的波妞", result.expanded_queries)
        self.assertIsNotNone(result.resolved_subject)
        self.assertEqual(result.resolved_subject.subject_id, 101)

    @patch("aqsd.title_resolver.search_bangumi_titles")
    def test_low_confidence_bangumi_subject_does_not_expand_search_queries(self, mock_search_bangumi) -> None:
        mock_search_bangumi.return_value = [
            BangumiTitleMetadata(subject_id=201, name="Another Show", name_cn="另一个作品", aliases=["Another Show", "另一个作品"]),
            BangumiTitleMetadata(subject_id=202, name="Completely Different", name_cn="完全无关", aliases=["Completely Different", "完全无关"]),
        ]

        result = resolve_title_query(
            "上伊那牡丹，酒醉身姿似百合花般",
            [],
            bangumi_settings=_BangumiSettings(enabled=True),
            anilist_settings=_AniListSettings(enabled=False),
        )

        self.assertEqual(result.expanded_queries, ["上伊那牡丹，酒醉身姿似百合花般"])
        self.assertIsNone(result.resolved_subject)
        self.assertTrue(result.rejected_subjects)

    @patch("aqsd.title_resolver.search_bangumi_titles")
    def test_legacy_bangumi_alias_cache_is_ignored_and_re_ranked(self, mock_search_bangumi) -> None:
        mock_search_bangumi.return_value = [
            BangumiTitleMetadata(
                subject_id=101,
                name="上伊那ぼたん、酔へる姿は百合の花",
                name_cn="上伊那牡丹，醉姿如百合",
                aliases=[
                    "上伊那ぼたん、酔へる姿は百合の花",
                    "上伊那牡丹，醉姿如百合",
                    "Kamiina Botan, Yoeru Sugata wa Yuri no Hana",
                ],
            )
        ]
        cache = _FakeCache(
            aliases_by_source={
                BANGUMI_CACHE_SOURCE: [
                    "上伊那ぼたん、酔へる姿は百合の花",
                    "上伊那牡丹，醉姿如百合",
                    "Kamiina Botan, Yoeru Sugata wa Yuri no Hana",
                    "上級生（じょうきゅうせい）",
                    "The Upper Classman",
                    "Minna no Uta",
                    "Joukyuusei",
                    "上前线",
                    "崖の上のポニョ",
                    "崖上的波妞",
                ]
            }
        )

        result = resolve_title_query(
            "上伊那牡丹，酒醉身姿似百合花般",
            [],
            bangumi_settings=_BangumiSettings(enabled=True),
            anilist_settings=_AniListSettings(enabled=False),
            cache=cache,
        )

        self.assertEqual(result.source, "bangumi")
        self.assertEqual(cache.deleted, ("上伊那牡丹，酒醉身姿似百合花般", BANGUMI_CACHE_SOURCE))
        self.assertNotIn("The Upper Classman", result.expanded_queries)
        self.assertNotIn("Minna no Uta", result.expanded_queries)
        self.assertNotIn("崖上的波妞", result.expanded_queries)

    def test_cached_structured_details_preserve_search_eligibility_and_confidence(self) -> None:
        cache = _FakeCache(
            metadata_by_source={
                BANGUMI_CACHE_SOURCE: {
                    "schema_version": 2,
                    "query": "尖帽子的魔法工房",
                    "source": "bangumi",
                    "created_at": "2026-05-13T00:00:00+00:00",
                    "resolved_subject": {
                        "source": "bangumi",
                        "subject_id": 301,
                        "canonical": "とんがり帽子のアトリエ",
                        "confidence": 0.94,
                    },
                    "expanded_query_details": [
                        {
                            "text": "尖帽子的魔法工房",
                            "source": "original",
                            "confidence": 1.0,
                            "language": "zh",
                            "alias_confidence": 1.0,
                            "search_eligible": True,
                            "search_tier": "secondary",
                        },
                        {
                            "text": "Witch Hat Atelier",
                            "source": "bangumi",
                            "confidence": 0.83,
                            "language": "en",
                            "subject_id": 301,
                            "subject_confidence": 0.94,
                            "alias_confidence": 0.83,
                            "search_eligible": True,
                            "search_tier": "primary",
                        },
                        {
                            "text": "Magic Hat Studio",
                            "source": "bangumi",
                            "confidence": 0.21,
                            "language": "en",
                            "subject_id": 301,
                            "subject_confidence": 0.94,
                            "alias_confidence": 0.21,
                            "search_eligible": False,
                            "search_tier": "display_only",
                        },
                    ],
                    "rejected_subjects": [],
                }
            }
        )

        result = resolve_title_query(
            "尖帽子的魔法工房",
            [],
            bangumi_settings=_BangumiSettings(enabled=True),
            anilist_settings=_AniListSettings(enabled=False),
            cache=cache,
        )

        self.assertEqual(result.source, "bangumi-cache")
        self.assertIn("Witch Hat Atelier", result.expanded_queries)
        self.assertNotIn("Magic Hat Studio", result.expanded_queries)
        details = {item.text: item for item in result.expanded_query_details}
        self.assertEqual(details["Witch Hat Atelier"].confidence, 0.83)
        self.assertFalse(details["Magic Hat Studio"].search_eligible)

    @patch("aqsd.title_resolver.search_bangumi_titles")
    def test_alias_confidence_and_language_detection_are_not_uniform(self, mock_search_bangumi) -> None:
        mock_search_bangumi.return_value = [
            BangumiTitleMetadata(
                subject_id=301,
                name="とんがり帽子のアトリエ",
                name_cn="尖帽子的魔法工房",
                aliases=[
                    "魔法帽的工作室",
                    "Atelier of Witch Hat",
                    "Witch Hat Atelier",
                    "Tongari Boushi no Atelier",
                ],
            )
        ]

        result = resolve_title_query(
            "尖帽子的魔法工房",
            [],
            bangumi_settings=_BangumiSettings(enabled=True),
            anilist_settings=_AniListSettings(enabled=False),
        )

        detail_map = {item.text: item for item in result.expanded_query_details}
        self.assertEqual(detail_map["Witch Hat Atelier"].language, "en")
        self.assertEqual(detail_map["Atelier of Witch Hat"].language, "en")
        self.assertEqual(detail_map["Tongari Boushi no Atelier"].language, "romaji")
        self.assertTrue(detail_map["とんがり帽子のアトリエ"].search_eligible)
        self.assertTrue(detail_map["魔法帽的工作室"].search_eligible)
        confidences = {
            detail_map["とんがり帽子のアトリエ"].confidence,
            detail_map["魔法帽的工作室"].confidence,
            detail_map["Witch Hat Atelier"].confidence,
            detail_map["Tongari Boushi no Atelier"].confidence,
        }
        self.assertGreater(len(confidences), 1)

    @patch("aqsd.title_resolver.search_bangumi_titles")
    def test_english_and_romaji_titles_are_labeled_separately(self, mock_search_bangumi) -> None:
        mock_search_bangumi.return_value = [
            BangumiTitleMetadata(
                subject_id=401,
                name="女神『異世界転生何になりたいですか』俺「勇者の肋骨で」",
                name_cn="女神“异世界转生想成为什么”我“勇者的肋骨”",
                aliases=[
                    "My Ribdiculous Reincarnation",
                    'Megami "Isekai Tensei Nani ni Naritai Desuka" Ore "Yuusha no Rokkotsu de"',
                ],
            )
        ]

        result = resolve_title_query(
            "女神异世界转生想成为什么我勇者的肋骨",
            [],
            bangumi_settings=_BangumiSettings(enabled=True),
            anilist_settings=_AniListSettings(enabled=False),
        )

        detail_map = {item.text: item for item in result.expanded_query_details}
        self.assertEqual(detail_map["My Ribdiculous Reincarnation"].language, "en")
        self.assertEqual(
            detail_map['Megami "Isekai Tensei Nani ni Naritai Desuka" Ore "Yuusha no Rokkotsu de"'].language,
            "romaji",
        )


if __name__ == "__main__":
    unittest.main()
