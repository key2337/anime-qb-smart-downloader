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
        timeout=30,
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


def build_keyword_rss_url(base_url: str, keyword: str) -> str:
    """Build a keyword-filtered RSS URL for dmhy-style sources."""
    from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

    parsed = urlparse(base_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["keyword"] = [keyword]
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def fetch_rss(source: Any, keyword: str | None = None) -> list[Candidate]:
    source_name = source.name if hasattr(source, "name") else source["name"]
    source_url = source.url if hasattr(source, "url") else source["url"]

    if keyword:
        source_url = build_keyword_rss_url(source_url, keyword)

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

        magnet = _extract_magnet(entry)
        info_hash = _extract_info_hash_from_magnet(magnet)

        items.append(
            Candidate(
                title=title,
                url=url,
                source=source_name,
                magnet=magnet,
                info_hash=info_hash,
                published_at=parse_datetime(published),
                seeders=extract_seeders(entry),
            )
        )

    return items


def _extract_magnet(entry: dict[str, Any]) -> str | None:
    for link in entry.get("links", []):
        if link.get("type") == "application/x-bittorrent":
            href = link.get("href", "")
            if href.casefold().startswith("magnet:"):
                return href
    for link in entry.get("links", []):
        href = link.get("href", "")
        if href.casefold().startswith("magnet:"):
            return href
    return None


def _extract_info_hash_from_magnet(magnet: str | None) -> str | None:
    if not magnet:
        return None
    import re
    match = re.search(r"btih:([A-Za-z0-9]+)", magnet)
    if match:
        return _normalize_info_hash(match.group(1))
    return None


def _normalize_info_hash(raw: str) -> str:
    """Convert info_hash to lowercase hex. Handles Base32 (32 chars) and hex (40 chars)."""
    import base64
    stripped = raw.strip()
    if len(stripped) == 32:
        pad = 8 - (len(stripped) % 8)
        if pad == 8:
            pad = 0
        try:
            raw_bytes = base64.b32decode(stripped.upper() + "=" * pad)
            return raw_bytes.hex().casefold()
        except Exception:
            pass
    return stripped.casefold()
