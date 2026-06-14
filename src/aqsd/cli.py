from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import TextIO

from loguru import logger

from aqsd.config import AppConfig
from aqsd.discovery import SearchRequest, discover_search_candidates
from aqsd.database import Database
from aqsd.models import Candidate, DownloadTask, SearchDiagnostics
from aqsd.probe import probe_candidates
from aqsd.qbittorrent import QBittorrentClient
from aqsd.scorer import render_score_reason
from aqsd.utils import build_task_tag


MAX_REASON_CANDIDATES = 5
MAX_REASON_LINES = 3


def run_search_command(args: argparse.Namespace, config: AppConfig, out: TextIO | None = None) -> int:
    stream = out or sys.stdout
    request = build_search_request(args)
    result = discover_search_candidates(config, request)

    if not result.candidates:
        _print_no_candidates_diagnostics(stream, result.diagnostics)
        return 0

    print(_build_header(), file=stream)
    for index, candidate in enumerate(result.candidates, start=1):
        print(_format_candidate_row(index, candidate), file=stream)
    print("", file=stream)
    for index, candidate in enumerate(result.candidates[:MAX_REASON_CANDIDATES], start=1):
        _print_candidate_breakdown(stream, candidate, index=index)
    return 0


def run_download_command(args: argparse.Namespace, config: AppConfig, out: TextIO | None = None) -> int:
    stream = out or sys.stdout
    request = build_search_request(args)
    result = discover_search_candidates(config, request)

    if not result.candidates:
        _print_no_candidates_diagnostics(stream, result.diagnostics)
        return 1

    ranked_candidates = sorted(result.candidates, key=lambda item: (item.score, item.seeders), reverse=True)
    best = ranked_candidates[0]
    best.task_tag = best.task_tag or build_task_tag(best.anime_name or request.query or "anime", best.episode or "00")

    if getattr(args, "dry_run", False):
        _print_candidate_breakdown(stream, best, heading="Selected candidate")
        print("Dry-run only: not adding torrent.", file=stream)
        return 0

    db = Database(config.app.database)
    qb = QBittorrentClient(
        base_url=config.qb.base_url,
        username=config.qb.username,
        password=config.qb.password,
    )

    try:
        qb.login()
        already_submitted = False

        if getattr(args, "probe", False) or config.probe_policy.enabled:
            probe_result = probe_candidates(ranked_candidates, qb, config.probe_policy)
            if probe_result.selected is not None:
                best = probe_result.selected
                best.task_tag = probe_result.selected_tag
                already_submitted = True

        _print_candidate_breakdown(stream, best, heading="Selected candidate")

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


def _print_candidate_breakdown(
    stream: TextIO,
    candidate: Candidate,
    *,
    heading: str | None = None,
    index: int | None = None,
) -> None:
    if heading:
        print(f"{heading}:", file=stream)
    elif index is not None:
        print(f"#{index} {candidate.title}", file=stream)
    else:
        print(candidate.title, file=stream)

    if heading:
        print(candidate.title, file=stream)
    print(f"Score: {candidate.score:.1f}", file=stream)
    if candidate.breakdown and candidate.breakdown.reasons:
        print("Reasons:", file=stream)
        for reason in candidate.breakdown.reasons[:MAX_REASON_LINES]:
            print(f"  {render_score_reason(reason)}", file=stream)
    print("", file=stream)


def _print_no_candidates_diagnostics(stream: TextIO, diagnostics: SearchDiagnostics | None) -> None:
    print("No good candidates found.", file=stream)
    if diagnostics is None:
        return

    if (
        diagnostics.candidate_count_before_filter is not None
        and diagnostics.candidate_count_before_filter > 0
        and (diagnostics.candidate_count_after_filter or 0) == 0
    ):
        print("", file=stream)
        print("Candidates were found, but all were filtered out.", file=stream)

    print("", file=stream)
    print("Tried queries:", file=stream)
    for value in diagnostics.expanded_queries or [diagnostics.original_query]:
        print(f"- {value}", file=stream)

    print("", file=stream)
    print("Sources:", file=stream)
    if diagnostics.sources:
        for source in diagnostics.sources:
            print(f"- {source}", file=stream)
    else:
        print("- none", file=stream)

    print("", file=stream)
    print("Active filters:", file=stream)
    if diagnostics.active_filters:
        for key, value in diagnostics.active_filters.items():
            print(f"- {key}: {value}", file=stream)
    else:
        print("- none", file=stream)

    print("", file=stream)
    print("Suggestions:", file=stream)
    for suggestion in diagnostics.suggestions or [f'Try a different search query.']:
        print(f"- {suggestion}", file=stream)
