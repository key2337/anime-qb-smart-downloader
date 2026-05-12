from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Iterable
from typing import Any

import requests

from aqsd.config import AniListMetadataSourceSettings


ANILIST_QUERY = """
query ($search: String) {
  Page(page: 1, perPage: 5) {
    media(search: $search, type: ANIME) {
      title {
        romaji
        english
        native
      }
      synonyms
      seasonYear
      format
    }
  }
}
"""


@dataclass(slots=True)
class TitleMetadata:
    canonical: str
    aliases: list[str] = field(default_factory=list)
    romaji: str | None = None
    english: str | None = None
    native: str | None = None
    source: str = "anilist"
    confidence: float | None = None
    year: int | None = None
    format: str | None = None


def fetch_anilist_title_metadata(query: str, settings: AniListMetadataSourceSettings) -> list[TitleMetadata]:
    response = requests.post(
        settings.endpoint,
        json={"query": ANILIST_QUERY, "variables": {"search": query}},
        timeout=settings.timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    return parse_anilist_response(payload)


def parse_anilist_response(payload: dict[str, Any]) -> list[TitleMetadata]:
    media_items = payload.get("data", {}).get("Page", {}).get("media", []) or []
    results: list[TitleMetadata] = []

    for media in media_items:
        title = media.get("title") or {}
        title_values = [
            title.get("romaji"),
            title.get("english"),
            title.get("native"),
            *(media.get("synonyms") or []),
        ]
        aliases = _dedupe_non_empty(str(value) for value in title_values if value)
        if not aliases:
            continue

        results.append(
            TitleMetadata(
                canonical=aliases[0],
                aliases=aliases,
                romaji=title.get("romaji"),
                english=title.get("english"),
                native=title.get("native"),
                source="anilist",
                year=media.get("seasonYear"),
                format=media.get("format"),
            )
        )

    return results


def _dedupe_non_empty(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        stripped = value.strip()
        if not stripped or stripped.casefold() in seen:
            continue
        seen.add(stripped.casefold())
        result.append(stripped)
    return result
