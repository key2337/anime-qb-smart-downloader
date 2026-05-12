from __future__ import annotations

from time import struct_time
from typing import Any
from urllib.parse import urlencode

import feedparser
import requests

from aqsd.config import NyaaSearchSourceSettings
from aqsd.models import Candidate
from aqsd.rss import USER_AGENT, extract_seeders, parse_datetime


def build_nyaa_rss_url(
    settings: NyaaSearchSourceSettings,
    query: str,
    *,
    category: str | None = None,
    page: int = 1,
) -> str:
    base_url = settings.base_url.rstrip("/")
    params = {
        "page": "rss",
        "q": query,
        "c": category or settings.default_category,
    }
    if page > 1:
        params["p"] = str(page)
    return f"{base_url}/?{urlencode(params)}"


def fetch_nyaa_candidates(
    settings: NyaaSearchSourceSettings,
    query: str,
    *,
    category: str | None = None,
    limit: int | None = None,
    page: int = 1,
) -> list[Candidate]:
    url = build_nyaa_rss_url(settings, query, category=category, page=page)
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=settings.timeout_seconds,
    )
    response.raise_for_status()

    feed = feedparser.parse(response.content)
    candidates: list[Candidate] = []
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        candidate_url = entry.get("link") or entry.get("id") or ""
        published = _published_value(entry)
        if not title or not candidate_url:
            continue

        candidates.append(
            Candidate(
                title=title,
                url=candidate_url,
                source="nyaa",
                published_at=parse_datetime(published),
                seeders=extract_seeders(entry),
            )
        )
        if limit is not None and len(candidates) >= limit:
            break

    return candidates


def _published_value(entry: dict[str, Any]) -> str | struct_time | None:
    return (
        entry.get("published_parsed")
        or entry.get("updated_parsed")
        or entry.get("published")
        or entry.get("updated")
    )
