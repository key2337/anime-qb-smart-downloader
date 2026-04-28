from __future__ import annotations

import io
import unittest
from argparse import Namespace
from datetime import datetime, timezone
from unittest.mock import patch

from aqsd.cli import build_search_request, run_search_command
from aqsd.config import AppConfig
from aqsd.discovery import DiscoveryResult
from aqsd.models import Candidate


def _build_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "qbittorrent": {
                "base_url": "http://127.0.0.1:8080",
                "username": "user",
                "password": "pass",
            }
        }
    )


class SearchCliTests(unittest.TestCase):
    def test_build_search_request_maps_cli_arguments(self) -> None:
        args = Namespace(
            query="Example Anime",
            episodes=["01", "02"],
            resolution="1080p",
            groups=["LoliHouse", "SubsPlease"],
            subtitle="embedded",
            raw_only=True,
            min_seeders=5,
            limit=10,
        )

        request = build_search_request(args)

        self.assertEqual(request.query, "Example Anime")
        self.assertEqual(request.episodes, ["01", "02"])
        self.assertEqual(request.resolution, "1080p")
        self.assertEqual(request.groups, ["LoliHouse", "SubsPlease"])
        self.assertEqual(request.subtitle_type, "embedded")
        self.assertTrue(request.raw_only)
        self.assertEqual(request.min_seeders, 5)
        self.assertEqual(request.limit, 10)

    def test_build_search_request_maps_any_subtitle_to_none(self) -> None:
        args = Namespace(
            query="Example Anime",
            episodes=[],
            resolution=None,
            groups=[],
            subtitle="any",
            raw_only=False,
            min_seeders=0,
            limit=None,
        )

        request = build_search_request(args)

        self.assertIsNone(request.subtitle_type)

    @patch("aqsd.cli.discover_search_candidates")
    def test_run_search_command_only_displays_results(self, mock_discover_search_candidates) -> None:
        mock_discover_search_candidates.return_value = DiscoveryResult(
            candidates=[
                Candidate(
                    title="[LoliHouse] Example Anime - 01 [1080p][CHS]",
                    url="https://example.test/1",
                    source="mock",
                    episode="01",
                    resolution="1080p",
                    group="LoliHouse",
                    subtitle_type="embedded",
                    seeders=12,
                    score=123.4,
                    published_at=datetime(2026, 4, 28, 9, 30, tzinfo=timezone.utc),
                )
            ]
        )
        args = Namespace(
            query="Example Anime",
            episodes=[],
            resolution=None,
            groups=[],
            subtitle="any",
            raw_only=False,
            min_seeders=0,
            limit=None,
        )
        output = io.StringIO()

        run_search_command(args, _build_config(), out=output)

        rendered = output.getvalue()
        self.assertIn("#\ttitle\tepisode\tresolution\tgroup\tsubtitle\tseeders\tpublished_at\tscore\tsource", rendered)
        self.assertIn("[LoliHouse] Example Anime - 01 [1080p][CHS]", rendered)
        self.assertIn("\t01\t1080p\tLoliHouse\tembedded\t12\t2026-04-28 09:30:00\t123.4\tmock", rendered)
        mock_discover_search_candidates.assert_called_once()

    @patch("aqsd.main.run_search_command")
    @patch("aqsd.main.run_once")
    @patch("aqsd.main.run_dry_run")
    @patch("aqsd.main.check_connections")
    @patch("aqsd.main.load_config")
    @patch("sys.argv", ["aqsd", "search", "Example Anime", "--episode", "01", "--resolution", "1080p", "--group", "LoliHouse", "--subtitle", "embedded", "--raw-only"])
    def test_main_dispatches_search_without_running_download_flow(
        self,
        mock_load_config,
        mock_check_connections,
        mock_run_dry_run,
        mock_run_once,
        mock_run_search_command,
    ) -> None:
        from aqsd.main import main

        config = _build_config()
        mock_load_config.return_value = config

        main()

        mock_run_search_command.assert_called_once()
        called_args, called_config = mock_run_search_command.call_args.args
        self.assertEqual(called_args.query, "Example Anime")
        self.assertEqual(called_args.episodes, ["01"])
        self.assertEqual(called_args.resolution, "1080p")
        self.assertEqual(called_args.groups, ["LoliHouse"])
        self.assertEqual(called_args.subtitle, "embedded")
        self.assertTrue(called_args.raw_only)
        self.assertIs(called_config, config)
        mock_run_once.assert_not_called()
        mock_run_dry_run.assert_not_called()
        mock_check_connections.assert_not_called()


if __name__ == "__main__":
    unittest.main()
