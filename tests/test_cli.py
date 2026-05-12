from __future__ import annotations

import io
import unittest
from argparse import Namespace
from datetime import datetime, timezone
from unittest.mock import patch

from aqsd.cli import build_search_request, run_download_command, run_resolve_title_command, run_search_command
from aqsd.config import AppConfig
from aqsd.discovery import DiscoveryResult
from aqsd.models import Candidate, ScoreBreakdown, ScoreReason, SearchDiagnostics
from aqsd.probe import ProbeResult
from aqsd.title_resolver import TitleResolution


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


def _build_alias_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "qbittorrent": {
                "base_url": "http://127.0.0.1:8080",
                "username": "user",
                "password": "pass",
            },
            "rss_sources": [
                {"name": "mock", "url": "https://example.test/rss.xml", "enabled": True},
            ],
            "title_aliases": [
                {
                    "canonical": "一拳超人",
                    "aliases": ["一拳超人", "One Punch Man", "One-Punch Man", "ワンパンマン"],
                }
            ],
        }
    )


class SearchCliTests(unittest.TestCase):
    @staticmethod
    def _build_breakdown(*messages: tuple[str, float, str]) -> ScoreBreakdown:
        reasons = [ScoreReason(code=code, delta=delta, message=message) for code, delta, message in messages]
        return ScoreBreakdown(total=sum(reason.delta for reason in reasons), reasons=reasons)

    @staticmethod
    def _build_diagnostics(**overrides: object) -> SearchDiagnostics:
        defaults = {
            "original_query": "Example Anime",
            "expanded_queries": ["Example Anime", "Example"],
            "sources": ["RSS", "Nyaa"],
            "active_filters": {},
            "candidate_count_before_filter": 0,
            "candidate_count_after_filter": 0,
            "suggestions": ['Try running: aqsd resolve-title "Example Anime"'],
        }
        defaults.update(overrides)
        return SearchDiagnostics(**defaults)

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
                    breakdown=self._build_breakdown(
                        ("title_match", 25.0, "title matched: Example Anime"),
                        ("episode_match", 20.0, "episode matched: 01"),
                    ),
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
        self.assertIn("Reasons:", rendered)
        self.assertIn("+25 title matched: Example Anime", rendered)
        mock_discover_search_candidates.assert_called_once()

    @patch("aqsd.cli.discover_search_candidates")
    def test_run_search_command_without_candidates_displays_diagnostics(self, mock_discover_search_candidates) -> None:
        mock_discover_search_candidates.return_value = DiscoveryResult(
            candidates=[],
            diagnostics=self._build_diagnostics(
                original_query="Angel Beats!",
                expanded_queries=["Angel Beats!"],
                sources=["RSS", "Nyaa", "Torznab"],
                active_filters={"episode": "01", "resolution": "1080p"},
                suggestions=[
                    'Try running: aqsd resolve-title "Angel Beats!"',
                    "Check whether the episode number is correct.",
                ],
            ),
        )
        args = Namespace(
            query="Angel Beats!",
            episodes=["01"],
            resolution="1080p",
            groups=[],
            subtitle="any",
            raw_only=False,
            min_seeders=0,
            limit=None,
        )
        output = io.StringIO()

        exit_code = run_search_command(args, _build_config(), out=output)

        rendered = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("No good candidates found.", rendered)
        self.assertIn("Tried queries:", rendered)
        self.assertIn("- Angel Beats!", rendered)
        self.assertIn("Sources:", rendered)
        self.assertIn("- Torznab", rendered)
        self.assertIn("Suggestions:", rendered)

    @patch("aqsd.cli.discover_search_candidates")
    def test_run_search_command_without_candidates_shows_relax_filter_suggestion(self, mock_discover_search_candidates) -> None:
        mock_discover_search_candidates.return_value = DiscoveryResult(
            candidates=[],
            diagnostics=self._build_diagnostics(
                active_filters={"group": "LoliHouse", "subtitle": "embedded", "raw_only": True},
                suggestions=[
                    "Try removing --group or using a different fansub group.",
                    "Try relaxing subtitle, RAW, or batch filters.",
                ],
            ),
        )
        args = Namespace(
            query="Example Anime",
            episodes=[],
            resolution=None,
            groups=["LoliHouse"],
            subtitle="embedded",
            raw_only=True,
            min_seeders=0,
            limit=None,
        )
        output = io.StringIO()

        run_search_command(args, _build_config(), out=output)

        rendered = output.getvalue()
        self.assertIn("Try relaxing subtitle, RAW, or batch filters.", rendered)

    @patch("aqsd.cli.resolve_search_title")
    def test_run_resolve_title_command_displays_expanded_queries(self, mock_resolve_search_title) -> None:
        mock_resolve_search_title.return_value = TitleResolution(
            canonical="Angel Beats!",
            expanded_queries=["天使的心跳", "Angel Beats!", "エンジェルビーツ"],
            source="anilist",
            local_alias_matched=False,
            cache_hit=False,
            anilist_enabled=True,
            anilist_attempted=True,
        )
        args = Namespace(query="天使的心跳")
        output = io.StringIO()

        exit_code = run_resolve_title_command(args, _build_config(), out=output)

        rendered = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("query: 天使的心跳", rendered)
        self.assertIn("canonical: Angel Beats!", rendered)
        self.assertIn("source: anilist", rendered)
        self.assertIn("anilist_enabled: yes", rendered)
        self.assertIn("cache_hit: no", rendered)
        self.assertIn("- Angel Beats!", rendered)
        mock_resolve_search_title.assert_called_once()

    @patch("aqsd.main.run_search_command")
    @patch("aqsd.main.run_resolve_title_command")
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
        mock_run_resolve_title_command,
        mock_run_search_command,
    ) -> None:
        from aqsd.main import main

        config = _build_config()
        mock_load_config.return_value = config
        mock_run_search_command.return_value = 0

        with self.assertRaises(SystemExit) as exc:
            main()

        mock_run_search_command.assert_called_once()
        self.assertEqual(exc.exception.code, 0)
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
        mock_run_resolve_title_command.assert_not_called()

    @patch("aqsd.main.run_download_command")
    @patch("aqsd.main.run_search_command")
    @patch("aqsd.main.run_resolve_title_command")
    @patch("aqsd.main.run_once")
    @patch("aqsd.main.run_dry_run")
    @patch("aqsd.main.check_connections")
    @patch("aqsd.main.load_config")
    @patch("sys.argv", ["aqsd", "resolve-title", "天使的心跳"])
    def test_main_dispatches_resolve_title_without_running_other_modes(
        self,
        mock_load_config,
        mock_check_connections,
        mock_run_dry_run,
        mock_run_once,
        mock_run_resolve_title_command,
        mock_run_search_command,
        mock_run_download_command,
    ) -> None:
        from aqsd.main import main

        config = _build_config()
        mock_load_config.return_value = config
        mock_run_resolve_title_command.return_value = 0

        with self.assertRaises(SystemExit) as exc:
            main()

        self.assertEqual(exc.exception.code, 0)
        mock_run_resolve_title_command.assert_called_once()
        called_args, called_config = mock_run_resolve_title_command.call_args.args
        self.assertEqual(called_args.query, "天使的心跳")
        self.assertIs(called_config, config)
        mock_run_search_command.assert_not_called()
        mock_run_download_command.assert_not_called()
        mock_run_once.assert_not_called()
        mock_run_dry_run.assert_not_called()
        mock_check_connections.assert_not_called()

    @patch("aqsd.cli.QBittorrentClient")
    @patch("aqsd.cli.Database")
    @patch("aqsd.cli.discover_search_candidates")
    def test_run_download_command_chooses_highest_score_and_records_submitted(
        self,
        mock_discover_search_candidates,
        mock_database_cls,
        mock_qb_cls,
    ) -> None:
        better = Candidate(
            title="[LoliHouse] Example Anime - 01 [1080p][CHS]",
            url="https://example.test/1",
            source="mock",
            episode="01",
            anime_name="Example Anime",
            category="Anime",
            save_path="/downloads/anime",
            seeders=8,
            score=120.0,
            breakdown=self._build_breakdown(
                ("title_match", 25.0, "title matched: Example Anime"),
                ("episode_match", 20.0, "episode matched: 01"),
            ),
        )
        worse = Candidate(
            title="[Other] Example Anime - 01 [1080p][CHS]",
            url="https://example.test/2",
            source="mock",
            episode="01",
            anime_name="Example Anime",
            category="Anime",
            save_path="/downloads/anime",
            seeders=50,
            score=80.0,
            breakdown=self._build_breakdown(("title_match", 25.0, "title matched: Example Anime")),
        )
        mock_discover_search_candidates.return_value = DiscoveryResult(candidates=[worse, better])
        mock_db = mock_database_cls.return_value
        mock_db.create_download_task.return_value = 123
        mock_qb = mock_qb_cls.return_value
        output = io.StringIO()
        args = Namespace(
            query="Example Anime",
            episodes=["01"],
            resolution="1080p",
            groups=[],
            subtitle="any",
            raw_only=False,
            min_seeders=0,
            limit=None,
        )

        exit_code = run_download_command(args, _build_config(), out=output)

        self.assertEqual(exit_code, 0)
        mock_qb.login.assert_called_once()
        mock_qb.add_torrent.assert_called_once_with(
            better.url,
            category=better.category,
            save_path=better.save_path,
            tags=better.task_tag,
        )
        mock_db.create_download_task.assert_called_once()
        recorded_task = mock_db.create_download_task.call_args.args[0]
        self.assertEqual(recorded_task.title, better.title)
        self.assertEqual(recorded_task.selection_mode, "manual")
        self.assertEqual(recorded_task.candidate_score, better.score)
        self.assertEqual(recorded_task.source, better.source)
        self.assertEqual(recorded_task.status, "submitted")
        self.assertNotIn(recorded_task.status, {"completed", "done"})
        mock_db.save_fallback_candidates.assert_called_once_with(123, [worse])
        self.assertIn("Selected candidate:", output.getvalue())
        self.assertIn("+20 episode matched: 01", output.getvalue())
        self.assertIn("Added torrent:", output.getvalue())

    @patch("aqsd.cli.QBittorrentClient")
    @patch("aqsd.cli.Database")
    @patch("aqsd.cli.discover_search_candidates")
    def test_run_download_command_returns_non_zero_when_no_candidates(
        self,
        mock_discover_search_candidates,
        mock_database_cls,
        mock_qb_cls,
    ) -> None:
        mock_discover_search_candidates.return_value = DiscoveryResult(
            candidates=[],
            diagnostics=self._build_diagnostics(
                candidate_count_before_filter=2,
                candidate_count_after_filter=0,
                active_filters={"group": "LoliHouse"},
                suggestions=["Try removing --group or using a different fansub group."],
            ),
        )
        output = io.StringIO()
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

        exit_code = run_download_command(args, _build_config(), out=output)

        self.assertEqual(exit_code, 1)
        self.assertIn("No good candidates found.", output.getvalue())
        self.assertIn("Candidates were found, but all were filtered out.", output.getvalue())
        mock_database_cls.assert_not_called()
        mock_qb_cls.assert_not_called()

    @patch("aqsd.cli.QBittorrentClient")
    @patch("aqsd.cli.Database")
    @patch("aqsd.cli.discover_search_candidates")
    def test_run_download_command_does_not_record_success_when_qb_add_fails(
        self,
        mock_discover_search_candidates,
        mock_database_cls,
        mock_qb_cls,
    ) -> None:
        mock_discover_search_candidates.return_value = DiscoveryResult(
            candidates=[
                Candidate(
                    title="[LoliHouse] Example Anime - 01 [1080p][CHS]",
                    url="https://example.test/1",
                    source="mock",
                    episode="01",
                    anime_name="Example Anime",
                    category="Anime",
                    save_path="/downloads/anime",
                    score=100.0,
                    breakdown=self._build_breakdown(("title_match", 25.0, "title matched: Example Anime")),
                )
            ]
        )
        mock_qb = mock_qb_cls.return_value
        mock_qb.add_torrent.side_effect = RuntimeError("boom")
        mock_db = mock_database_cls.return_value
        output = io.StringIO()
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

        exit_code = run_download_command(args, _build_config(), out=output)

        self.assertEqual(exit_code, 1)
        self.assertIn("Failed to add torrent: boom", output.getvalue())
        mock_db.create_download_task.assert_not_called()
        mock_db.save_fallback_candidates.assert_not_called()

    @patch("aqsd.main.run_download_command")
    @patch("aqsd.main.run_search_command")
    @patch("aqsd.main.run_once")
    @patch("aqsd.main.run_dry_run")
    @patch("aqsd.main.check_connections")
    @patch("aqsd.main.load_config")
    @patch("sys.argv", ["aqsd", "download", "Example Anime", "--episode", "01", "--resolution", "1080p", "--group", "LoliHouse", "--subtitle", "embedded", "--raw-only", "--probe"])
    def test_main_dispatches_download_without_running_other_modes(
        self,
        mock_load_config,
        mock_check_connections,
        mock_run_dry_run,
        mock_run_once,
        mock_run_search_command,
        mock_run_download_command,
    ) -> None:
        from aqsd.main import main

        config = _build_config()
        mock_load_config.return_value = config
        mock_run_download_command.return_value = 0

        with self.assertRaises(SystemExit) as exc:
            main()

        self.assertEqual(exc.exception.code, 0)
        mock_run_download_command.assert_called_once()
        called_args, called_config = mock_run_download_command.call_args.args
        self.assertEqual(called_args.query, "Example Anime")
        self.assertEqual(called_args.episodes, ["01"])
        self.assertEqual(called_args.resolution, "1080p")
        self.assertEqual(called_args.groups, ["LoliHouse"])
        self.assertEqual(called_args.subtitle, "embedded")
        self.assertTrue(called_args.raw_only)
        self.assertTrue(called_args.probe)
        self.assertIs(called_config, config)
        mock_run_search_command.assert_not_called()
        mock_run_once.assert_not_called()
        mock_run_dry_run.assert_not_called()
        mock_check_connections.assert_not_called()

    @patch("aqsd.cli.probe_candidates")
    @patch("aqsd.cli.QBittorrentClient")
    @patch("aqsd.cli.Database")
    @patch("aqsd.cli.discover_search_candidates")
    def test_run_download_command_falls_back_to_highest_score_when_probe_finds_no_winner(
        self,
        mock_discover_search_candidates,
        mock_database_cls,
        mock_qb_cls,
        mock_probe_candidates,
    ) -> None:
        better = Candidate(
            title="[LoliHouse] Example Anime - 01 [1080p][CHS]",
            url="https://example.test/1",
            source="mock",
            episode="01",
            anime_name="Example Anime",
            category="Anime",
            save_path="/downloads/anime",
            seeders=8,
            score=120.0,
        )
        worse = Candidate(
            title="[Other] Example Anime - 01 [1080p][CHS]",
            url="https://example.test/2",
            source="mock",
            episode="01",
            anime_name="Example Anime",
            category="Anime",
            save_path="/downloads/anime",
            seeders=50,
            score=80.0,
        )
        mock_discover_search_candidates.return_value = DiscoveryResult(candidates=[worse, better])
        mock_probe_candidates.return_value = ProbeResult(selected=None, selected_tag=None, attempts=[], scores={})
        mock_database_cls.return_value.create_download_task.return_value = 123
        args = Namespace(
            query="Example Anime",
            episodes=["01"],
            resolution="1080p",
            groups=[],
            subtitle="any",
            raw_only=False,
            min_seeders=0,
            limit=None,
            probe=True,
        )

        exit_code = run_download_command(args, _build_config(), out=io.StringIO())

        self.assertEqual(exit_code, 0)
        mock_probe_candidates.assert_called_once()
        mock_qb_cls.return_value.add_torrent.assert_called_once_with(
            better.url,
            category=better.category,
            save_path=better.save_path,
            tags=better.task_tag,
        )

    @patch("aqsd.cli.discover_search_candidates")
    def test_run_download_command_dry_run_displays_selected_candidate_reasons(self, mock_discover_search_candidates) -> None:
        mock_discover_search_candidates.return_value = DiscoveryResult(
            candidates=[
                Candidate(
                    title="[LoliHouse] Example Anime - 01 [1080p][CHS]",
                    url="https://example.test/1",
                    source="mock",
                    episode="01",
                    anime_name="Example Anime",
                    category="Anime",
                    save_path="/downloads/anime",
                    score=120.0,
                    breakdown=self._build_breakdown(
                        ("title_match", 25.0, "title matched: Example Anime"),
                        ("resolution_match", 15.0, "resolution matched: 1080p"),
                    ),
                )
            ]
        )
        args = Namespace(
            query="Example Anime",
            episodes=["01"],
            resolution="1080p",
            groups=[],
            subtitle="any",
            raw_only=False,
            min_seeders=0,
            limit=None,
            probe=False,
            dry_run=True,
        )
        output = io.StringIO()

        exit_code = run_download_command(args, _build_config(), out=output)

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("Selected candidate:", rendered)
        self.assertIn("Score: 120.0", rendered)
        self.assertIn("+15 resolution matched: 1080p", rendered)
        self.assertIn("Dry-run only: not adding torrent.", rendered)

    @patch("aqsd.cli.discover_search_candidates")
    def test_run_download_command_dry_run_without_candidates_displays_diagnostics(self, mock_discover_search_candidates) -> None:
        mock_discover_search_candidates.return_value = DiscoveryResult(
            candidates=[],
            diagnostics=self._build_diagnostics(
                original_query="天使的心跳",
                expanded_queries=["天使的心跳", "Angel Beats!"],
                sources=["RSS"],
                suggestions=[
                    'Try running: aqsd resolve-title "天使的心跳"',
                    "Add a local alias in config.yaml.",
                ],
            ),
        )
        args = Namespace(
            query="天使的心跳",
            episodes=[],
            resolution=None,
            groups=[],
            subtitle="any",
            raw_only=False,
            min_seeders=0,
            limit=None,
            probe=False,
            dry_run=True,
        )
        output = io.StringIO()

        exit_code = run_download_command(args, _build_config(), out=output)

        self.assertEqual(exit_code, 1)
        rendered = output.getvalue()
        self.assertIn("No good candidates found.", rendered)
        self.assertIn("Tried queries:", rendered)
        self.assertIn("- 天使的心跳", rendered)
        self.assertIn("Suggestions:", rendered)

    @patch("aqsd.cli.QBittorrentClient")
    @patch("aqsd.cli.Database")
    @patch("aqsd.discovery.fetch_rss")
    def test_run_download_command_uses_title_aliases_for_search(
        self,
        mock_fetch_rss,
        mock_database_cls,
        mock_qb_cls,
    ) -> None:
        mock_fetch_rss.return_value = [
            Candidate(
                title="[SubsPlease] One Punch Man - 01 [1080p][CHS]",
                url="https://example.test/opm-1",
                source="mock",
                seeders=5,
            )
        ]
        mock_database_cls.return_value.create_download_task.return_value = 123
        args = Namespace(
            query="一拳超人",
            episodes=[],
            resolution=None,
            groups=[],
            subtitle="any",
            raw_only=False,
            min_seeders=0,
            limit=None,
            probe=False,
        )

        exit_code = run_download_command(args, _build_alias_config(), out=io.StringIO())

        self.assertEqual(exit_code, 0)
        mock_qb_cls.return_value.add_torrent.assert_called_once()
        added_url = mock_qb_cls.return_value.add_torrent.call_args.args[0]
        self.assertEqual(added_url, "https://example.test/opm-1")


if __name__ == "__main__":
    unittest.main()
