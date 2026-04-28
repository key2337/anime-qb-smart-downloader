from __future__ import annotations

import argparse
import sys
import time

from loguru import logger

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
    return parser


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
