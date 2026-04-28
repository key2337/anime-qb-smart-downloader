from __future__ import annotations

import unittest
from unittest.mock import patch

from aqsd.config import AppConfig
from aqsd.discovery import SearchRequest, discover_rule_candidates, discover_search_candidates
from aqsd.models import Candidate


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
        self.assertEqual(len(db.saved_candidates), 1)
        self.assertEqual(db.saved_candidates[0].episode, "02")

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


if __name__ == "__main__":
    unittest.main()
