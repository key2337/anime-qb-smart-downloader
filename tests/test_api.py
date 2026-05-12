from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from aqsd.api import build_health_payload, create_api_app, run_server_command, serialize_candidate
from aqsd.config import AppConfig
from aqsd.discovery import DiscoveryResult
from aqsd.models import Candidate, ScoreBreakdown, ScoreReason, SearchDiagnostics

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - optional dependency
    TestClient = None


def _build_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "qbittorrent": {
                "base_url": "http://127.0.0.1:8080",
                "username": "user",
                "password": "pass",
            },
            "rss_sources": [{"name": "mock", "url": "https://example.test/rss.xml", "enabled": True}],
            "search_sources": {
                "nyaa": {"enabled": True},
                "torznab": {"enabled": False, "endpoints": []},
            },
            "metadata_sources": {
                "anilist": {"enabled": True},
            },
        }
    )


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed")
class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = _build_config()

    def test_api_app_can_create(self) -> None:
        app = create_api_app(self.config)
        self.assertIsNotNone(app)

    @patch("aqsd.api._probe_qb_status")
    def test_health_returns_json_with_ok(self, mock_probe_qb_status) -> None:
        mock_probe_qb_status.return_value = {"configured": True, "reachable": True}
        client = TestClient(create_api_app(self.config))

        response = client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("ok", payload)
        self.assertTrue(payload["ok"])

    @patch("aqsd.api.resolve_search_title")
    def test_resolve_title_returns_expanded_queries(self, mock_resolve_search_title) -> None:
        mock_resolve_search_title.return_value = Mock(
            expanded_queries=["天使的心跳", "Angel Beats!", "エンジェルビーツ"],
            source="anilist",
            local_alias_matched=False,
            cache_hit=False,
            anilist_attempted=True,
        )
        client = TestClient(create_api_app(self.config))

        response = client.post("/api/resolve-title", json={"query": "天使的心跳"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["expanded_queries"][0], "天使的心跳")
        self.assertIn("anilist", payload["sources"])

    def test_resolve_title_empty_query_returns_error(self) -> None:
        client = TestClient(create_api_app(self.config))

        response = client.post("/api/resolve-title", json={"query": "   "})

        self.assertEqual(response.status_code, 400)
        self.assertIn("query must not be empty", response.json()["detail"])

    @patch("aqsd.api.discover_search_candidates")
    def test_search_returns_candidates(self, mock_discover_search_candidates) -> None:
        candidate = Candidate(
            title="[LoliHouse] Example Anime - 01 [1080p][CHS]",
            url="magnet:?xt=urn:btih:ABC123",
            source="nyaa",
            score=87.0,
            seeders=12,
            published_at=datetime(2026, 4, 28, 9, 30, tzinfo=timezone.utc),
            episode="01",
            resolution="1080p",
            group="LoliHouse",
            subtitle_type="embedded",
            breakdown=ScoreBreakdown(
                total=87.0,
                reasons=[ScoreReason(code="title_match", delta=25.0, message="title matched: Example Anime")],
            ),
        )
        mock_discover_search_candidates.return_value = DiscoveryResult(
            candidates=[candidate],
            diagnostics=SearchDiagnostics(
                original_query="Example Anime",
                expanded_queries=["Example Anime"],
                sources=["RSS", "Nyaa"],
                active_filters={"episode": "01"},
                candidate_count_before_filter=1,
                candidate_count_after_filter=1,
                suggestions=[],
            ),
        )
        client = TestClient(create_api_app(self.config))

        response = client.post("/api/search", json={"query": "Example Anime", "episode": "01"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["candidates"]), 1)
        self.assertEqual(payload["candidates"][0]["rank"], 1)
        self.assertTrue(payload["candidates"][0]["breakdown"])

    @patch("aqsd.api.discover_search_candidates")
    def test_search_without_candidates_returns_diagnostics(self, mock_discover_search_candidates) -> None:
        mock_discover_search_candidates.return_value = DiscoveryResult(
            candidates=[],
            diagnostics=SearchDiagnostics(
                original_query="天使的心跳",
                expanded_queries=["天使的心跳", "Angel Beats!"],
                sources=["RSS", "Nyaa"],
                active_filters={"episode": "01"},
                candidate_count_before_filter=0,
                candidate_count_after_filter=0,
                suggestions=['Try running: aqsd resolve-title "天使的心跳"'],
            ),
        )
        client = TestClient(create_api_app(self.config))

        response = client.post("/api/search", json={"query": "天使的心跳", "episode": "01"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(payload["diagnostics"]["original_query"], "天使的心跳")
        self.assertIn("Angel Beats!", payload["diagnostics"]["expanded_queries"])

    def test_search_empty_query_returns_error(self) -> None:
        client = TestClient(create_api_app(self.config))

        response = client.post("/api/search", json={"query": ""})

        self.assertEqual(response.status_code, 400)
        self.assertIn("query must not be empty", response.json()["detail"])

class ApiCommandTests(unittest.TestCase):
    def test_serialize_candidate_includes_breakdown(self) -> None:
        candidate = Candidate(
            title="candidate",
            url="https://example.test/file.torrent",
            source="mock",
            breakdown=ScoreBreakdown(
                total=10.0,
                reasons=[ScoreReason(code="seeders", delta=10.0, message="seeders: 40")],
            ),
        )

        payload = serialize_candidate(candidate, rank=1)

        self.assertEqual(payload["rank"], 1)
        self.assertEqual(payload["breakdown"][0]["code"], "seeders")

    def test_run_server_command_reports_missing_dependencies(self) -> None:
        output = io.StringIO()
        with patch("aqsd.api._import_fastapi_runtime", side_effect=RuntimeError("API server dependencies are not installed. Please install fastapi and uvicorn.")):
            with redirect_stdout(output):
                exit_code = run_server_command(_build_config())

        self.assertEqual(exit_code, 1)
        self.assertIn("API server dependencies are not installed", output.getvalue())

    @patch("aqsd.api._probe_qb_status")
    def test_build_health_payload_handles_unreachable_qb(self, mock_probe_qb_status) -> None:
        mock_probe_qb_status.return_value = {
            "configured": True,
            "reachable": False,
            "error": "connection refused",
        }

        payload = build_health_payload(_build_config())

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["qbittorrent"]["error"], "connection refused")


if __name__ == "__main__":
    unittest.main()
