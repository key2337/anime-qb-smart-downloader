from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import TextIO

from loguru import logger

from aqsd.config import AppConfig
from aqsd.discovery import SearchRequest, discover_search_candidates, resolve_search_title
from aqsd.database import Database
from aqsd.models import Candidate, DownloadTask
from aqsd.probe import probe_candidates
from aqsd.qbittorrent import QBittorrentClient
from aqsd.utils import build_task_tag


def run_search_command(args: argparse.Namespace, config: AppConfig, out: TextIO | None = None) -> int:
    stream = out or sys.stdout
    request = build_search_request(args)
    result = discover_search_candidates(config, request)

    if not result.candidates:
        print("No candidates found.", file=stream)
        return 0

    print(_build_header(), file=stream)
    for index, candidate in enumerate(result.candidates, start=1):
        print(_format_candidate_row(index, candidate), file=stream)
    return 0


def run_download_command(args: argparse.Namespace, config: AppConfig, out: TextIO | None = None) -> int:
    stream = out or sys.stdout
    request = build_search_request(args)
    result = discover_search_candidates(config, request)

    if not result.candidates:
        print("No candidates found for download.", file=stream)
        return 1

    db = Database(config.app.database)
    qb = QBittorrentClient(
        base_url=config.qb.base_url,
        username=config.qb.username,
        password=config.qb.password,
    )

    try:
        qb.login()
        ranked_candidates = sorted(result.candidates, key=lambda item: (item.score, item.seeders), reverse=True)
        best = ranked_candidates[0]
        already_submitted = False

        if getattr(args, "probe", False) or config.probe_policy.enabled:
            probe_result = probe_candidates(ranked_candidates, qb, config.probe_policy)
            if probe_result.selected is not None:
                best = probe_result.selected
                best.task_tag = probe_result.selected_tag
                already_submitted = True

        if not best.task_tag:
            best.task_tag = build_task_tag(best.anime_name or request.query or "anime", best.episode or "00")

        if not already_submitted:
            qb.add_torrent(
                best.url,
                category=best.category,
                save_path=best.save_path,
                tags=best.task_tag,
            )
        task_id = db.create_download_task(
            DownloadTask(
                task_tag=best.task_tag,
                anime_name=best.anime_name or request.query,
                episode=best.episode or "00",
                title=best.title,
                url=best.url,
                selection_mode="manual",
                candidate_score=best.score,
                source=best.source,
                category=best.category,
                save_path=best.save_path,
                status="submitted",
            )
        )
        fallback_candidates = [candidate for candidate in ranked_candidates if candidate.url != best.url]
        db.save_fallback_candidates(task_id, fallback_candidates)
    except Exception as exc:
        logger.error("Failed to add torrent to qBittorrent: {}", exc)
        print(f"Failed to add torrent: {exc}", file=stream)
        return 1
    finally:
        db.close()

    print(f"Added torrent: {best.title}", file=stream)
    print(f"Task tag: {best.task_tag}", file=stream)
    return 0


def run_resolve_title_command(args: argparse.Namespace, config: AppConfig, out: TextIO | None = None) -> int:
    stream = out or sys.stdout
    resolution = resolve_search_title(config, args.query)

    print(f"query: {args.query}", file=stream)
    print(f"canonical: {resolution.canonical}", file=stream)
    print(f"source: {resolution.source}", file=stream)
    print(f"local_alias_matched: {'yes' if resolution.local_alias_matched else 'no'}", file=stream)
    print(f"anilist_enabled: {'yes' if resolution.anilist_enabled else 'no'}", file=stream)
    print(f"anilist_attempted: {'yes' if resolution.anilist_attempted else 'no'}", file=stream)
    print(f"cache_hit: {'yes' if resolution.cache_hit else 'no'}", file=stream)
    print("expanded_queries:", file=stream)
    for value in resolution.expanded_queries:
        print(f"- {value}", file=stream)
    return 0


def build_search_request(args: argparse.Namespace) -> SearchRequest:
    subtitle_type = None if args.subtitle == "any" else args.subtitle
    return SearchRequest(
        query=args.query,
        episodes=args.episodes,
        resolution=args.resolution,
        groups=args.groups,
        subtitle_type=subtitle_type,
        raw_only=args.raw_only,
        min_seeders=args.min_seeders,
        limit=args.limit,
    )


def _build_header() -> str:
    return "\t".join(
        [
            "#",
            "title",
            "episode",
            "resolution",
            "group",
            "subtitle",
            "seeders",
            "published_at",
            "score",
            "source",
        ]
    )


def _format_candidate_row(index: int, candidate: Candidate) -> str:
    published_at = _format_datetime(candidate.published_at)
    return "\t".join(
        [
            str(index),
            candidate.title,
            candidate.episode or "-",
            candidate.resolution or "-",
            candidate.group or "-",
            candidate.subtitle_type or "-",
            str(candidate.seeders),
            published_at,
            f"{candidate.score:.1f}",
            candidate.source,
        ]
    )


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.strftime("%Y-%m-%d %H:%M:%S")
