from __future__ import annotations

import argparse
import sys
import time

from loguru import logger

from aqsd.cli import run_download_command, run_resolve_title_command, run_search_command
from aqsd.config import load_config
from aqsd.database import Database
from aqsd.dryrun import run_dry_run
from aqsd.downloader import run_once
from aqsd.healthcheck import check_connections
from aqsd.monitor import DownloadMonitor
from aqsd.qbittorrent import QBittorrentClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Anime RSS smart downloader for qBittorrent.")
    parser.add_argument("--config", default="config.yaml", help="Path to the YAML config file.")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--daemon", action="store_true", help="Run continuously with the configured interval.")
    mode_group.add_argument("--check", action="store_true", help="Verify RSS and qB connectivity only.")
    mode_group.add_argument("--dry-run", action="store_true", help="Run RSS, parsing, matching, and scoring only.")
    subparsers = parser.add_subparsers(dest="command")
    search_parser = subparsers.add_parser("search", help="Search RSS candidates without downloading.")
    search_parser.add_argument("query", help="Anime name to search.")
    _add_search_like_arguments(search_parser)
    resolve_title_parser = subparsers.add_parser("resolve-title", help="Resolve a title into expanded search queries.")
    resolve_title_parser.add_argument("query", help="Anime name to resolve.")
    download_parser = subparsers.add_parser("download", help="Search candidates and add the best one to qBittorrent.")
    download_parser.add_argument("query", help="Anime name to search.")
    _add_search_like_arguments(download_parser)
    download_parser.add_argument("--probe", action="store_true", help="Probe top candidates in qB before choosing.")
    download_parser.add_argument("--dry-run", action="store_true", help="Show the selected candidate without adding it to qBittorrent.")
    return parser


def _add_search_like_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--episode",
        dest="episodes",
        action="append",
        default=[],
        help="Episode to keep. Repeat the flag to include multiple episodes.",
    )
    parser.add_argument("--resolution", help="Filter by resolution, for example 1080p.")
    parser.add_argument(
        "--group",
        dest="groups",
        action="append",
        default=[],
        help="Release group to keep. Repeat the flag to include multiple groups.",
    )
    parser.add_argument(
        "--subtitle",
        choices=["embedded", "external", "none", "unknown", "any"],
        default="any",
        help="Filter by subtitle type.",
    )
    parser.add_argument("--raw-only", action="store_true", help="Only keep RAW / subtitle-free releases.")
    parser.add_argument("--min-seeders", type=int, default=0, help="Minimum seeders required.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of results to show.")


def configure_logging(level: str) -> None:
    logger.remove()
    logger.add(sys.stderr, level=level.upper())


def run_daemon(config_path: str) -> None:
    config = load_config(config_path)
    configure_logging(config.app.log_level)

    db = Database(config.app.database)
    qb = QBittorrentClient(
        base_url=config.qb.base_url,
        username=config.qb.username,
        password=config.qb.password,
    )
    qb.login()
    monitor = DownloadMonitor(config, db, qb)

    try:
        while True:
            try:
                config = load_config(config_path)
                configure_logging(config.app.log_level)
                run_once(config, db=db, qb=qb)
                monitor.config = config
                monitor.scan()
            except Exception as exc:  # pragma: no cover - runtime safety
                logger.exception(exc)

            time.sleep(config.app.interval_seconds)
    finally:
        db.close()


def main() -> None:
    args = build_parser().parse_args()
    config = load_config(args.config)
    configure_logging(config.app.log_level)

    if args.command == "search":
        raise SystemExit(run_search_command(args, config))
        return

    if args.command == "resolve-title":
        raise SystemExit(run_resolve_title_command(args, config))
        return

    if args.command == "download":
        raise SystemExit(run_download_command(args, config))
        return

    if args.check:
        raise SystemExit(0 if check_connections(config) else 1)

    if args.dry_run:
        run_dry_run(config)
        return

    if args.daemon:
        run_daemon(args.config)
        return

    run_once(config)


if __name__ == "__main__":
    main()
