from __future__ import annotations

import unittest
from dataclasses import dataclass
from unittest.mock import patch

from aqsd.anilist import TitleMetadata
from aqsd.title_resolver import resolve_title_query


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


class _FakeCache:
    def __init__(self, aliases: list[str] | None = None) -> None:
        self.aliases = aliases
        self.saved: tuple[str, list[str], str, int] | None = None
        self.deleted: tuple[str, str] | None = None

    def get_title_alias_cache(self, query: str, source: str) -> list[str] | None:
        return self.aliases

    def save_title_alias_cache(self, query: str, aliases: list[str], source: str, ttl_days: int) -> None:
        self.saved = (query, aliases, source, ttl_days)

    def delete_title_alias_cache(self, query: str, source: str) -> None:
        self.deleted = (query, source)


class TitleResolverTests(unittest.TestCase):
    @patch("aqsd.title_resolver.fetch_anilist_title_metadata")
    def test_local_title_aliases_take_priority_over_anilist(self, mock_fetch_anilist) -> None:
        result = resolve_title_query(
            "天使的心跳",
            [_AliasGroup(canonical="Angel Beats!", aliases=["天使的心跳", "Angel Beats!"])],
            anilist_settings=_AniListSettings(enabled=True),
        )

        self.assertEqual(result.source, "local")
        self.assertTrue(result.local_alias_matched)
        self.assertEqual(result.expanded_queries, ["Angel Beats!", "天使的心跳"])
        mock_fetch_anilist.assert_not_called()

    @patch("aqsd.title_resolver.fetch_anilist_title_metadata")
    def test_queries_anilist_when_local_aliases_do_not_match(self, mock_fetch_anilist) -> None:
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
        cache = _FakeCache()

        result = resolve_title_query(
            "天使的心跳",
            [],
            anilist_settings=_AniListSettings(enabled=True),
            cache=cache,
        )

        self.assertEqual(result.source, "anilist")
        self.assertTrue(result.anilist_enabled)
        self.assertTrue(result.anilist_attempted)
        self.assertEqual(result.canonical, "Angel Beats!")
        self.assertIn("天使的心跳", result.expanded_queries)
        self.assertIn("Angel Beats!", result.expanded_queries)
        self.assertIn("エンジェルビーツ", result.expanded_queries)
        self.assertEqual(result.year, 2010)
        mock_fetch_anilist.assert_called_once()
        self.assertIsNotNone(cache.saved)

    @patch("aqsd.title_resolver.fetch_anilist_title_metadata")
    def test_incomplete_cache_does_not_block_valid_anilist_expansion(self, mock_fetch_anilist) -> None:
        mock_fetch_anilist.return_value = [
            TitleMetadata(
                canonical="Angel Beats!",
                aliases=["Angel Beats!", "エンジェルビーツ", "天使的心跳"],
                romaji="Angel Beats!",
                english="Angel Beats!",
                native="エンジェルビーツ",
            )
        ]
        cache = _FakeCache(["天使的心跳"])

        result = resolve_title_query(
            "天使的心跳",
            [],
            anilist_settings=_AniListSettings(enabled=True),
            cache=cache,
        )

        self.assertEqual(result.source, "anilist")
        self.assertIn("Angel Beats!", result.expanded_queries)
        self.assertEqual(cache.deleted, ("天使的心跳", "anilist-v3"))
        mock_fetch_anilist.assert_called_once()

    @patch("aqsd.title_resolver.fetch_anilist_title_metadata")
    def test_cache_hit_skips_anilist_request(self, mock_fetch_anilist) -> None:
        result = resolve_title_query(
            "天使的心跳",
            [],
            anilist_settings=_AniListSettings(enabled=True),
            cache=_FakeCache(["Angel Beats!", "エンジェルビーツ"]),
        )

        self.assertEqual(result.source, "anilist-cache")
        self.assertTrue(result.cache_hit)
        self.assertEqual(result.expanded_queries, ["天使的心跳", "Angel Beats!", "エンジェルビーツ"])
        mock_fetch_anilist.assert_not_called()

    @patch("aqsd.title_resolver.fetch_anilist_title_metadata")
    def test_anilist_failure_falls_back_to_original_query(self, mock_fetch_anilist) -> None:
        mock_fetch_anilist.side_effect = RuntimeError("network down")

        result = resolve_title_query(
            "天使的心跳",
            [],
            anilist_settings=_AniListSettings(enabled=True, cache_enabled=False),
        )

        self.assertEqual(result.source, "query")
        self.assertTrue(result.anilist_attempted)
        self.assertEqual(result.expanded_queries, ["天使的心跳"])

    @patch("aqsd.title_resolver.fetch_anilist_title_metadata")
    def test_disabled_anilist_does_not_request_metadata(self, mock_fetch_anilist) -> None:
        result = resolve_title_query("天使的心跳", [], anilist_settings=_AniListSettings(enabled=False))

        self.assertEqual(result.source, "query")
        self.assertFalse(result.anilist_attempted)
        self.assertEqual(result.expanded_queries, ["天使的心跳"])
        mock_fetch_anilist.assert_not_called()


if __name__ == "__main__":
    unittest.main()
