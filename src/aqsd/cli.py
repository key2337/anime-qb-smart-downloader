from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import TextIO

from aqsd.config import AppConfig
from aqsd.discovery import SearchRequest, discover_search_candidates
from aqsd.models import Candidate


def run_search_command(args: argparse.Namespace, config: AppConfig, out: TextIO | None = None) -> None:
    stream = out or sys.stdout
    request = build_search_request(args)
    result = discover_search_candidates(config, request)

    if not result.candidates:
        print("No candidates found.", file=stream)
        return

    print(_build_header(), file=stream)
    for index, candidate in enumerate(result.candidates, start=1):
        print(_format_candidate_row(index, candidate), file=stream)


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
