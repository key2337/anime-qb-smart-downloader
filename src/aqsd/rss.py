from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import struct_time
from typing import Any

import feedparser
import requests

from aqsd.models import Candidate


SEEDER_KEYS = ("seeders", "nyaa_seeders", "torrent_seeds", "torrentSeeders")
USER_AGENT = "aqsd/0.1.0"


def parse_datetime(value: str | struct_time | None) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, struct_time):
        return datetime(*value[:6], tzinfo=timezone.utc)

    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def extract_seeders(entry: dict[str, Any]) -> int:
    for key in SEEDER_KEYS:
        value = entry.get(key)
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _download_feed(url: str) -> requests.Response:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=10,
    )
    response.raise_for_status()
    return response


def inspect_rss(source: Any) -> dict[str, Any]:
    source_name = source.name if hasattr(source, "name") else source["name"]
    source_url = source.url if hasattr(source, "url") else source["url"]

    response = _download_feed(source_url)
    parsed = feedparser.parse(response.content)
    feed_version = getattr(parsed, "version", "")
    if not feed_version:
        raise RuntimeError("Response is not a valid RSS/Atom feed.")

    return {
        "name": source_name,
        "url": source_url,
        "status_code": response.status_code,
        "feed_title": parsed.feed.get("title", ""),
        "entries": len(parsed.entries),
        "feed_version": feed_version,
        "bozo": bool(getattr(parsed, "bozo", 0)),
        "bozo_exception": str(getattr(parsed, "bozo_exception", "")) if getattr(parsed, "bozo", 0) else "",
    }


def fetch_rss(source: Any) -> list[Candidate]:
    source_name = source.name if hasattr(source, "name") else source["name"]
    source_url = source.url if hasattr(source, "url") else source["url"]

    response = _download_feed(source_url)
    feed = feedparser.parse(response.content)
    items: list[Candidate] = []

    for entry in feed.entries:
        title = entry.get("title", "").strip()
        url = entry.get("link") or entry.get("id") or ""
        published = (
            entry.get("published_parsed")
            or entry.get("updated_parsed")
            or entry.get("published")
            or entry.get("updated")
        )

        if not title or not url:
            continue

        items.append(
            Candidate(
                title=title,
                url=url,
                source=source_name,
                published_at=parse_datetime(published),
                seeders=extract_seeders(entry),
            )
        )

    return items
