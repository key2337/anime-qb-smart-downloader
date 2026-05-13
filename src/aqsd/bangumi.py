from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import requests


BANGUMI_SEARCH_ENDPOINT = "https://api.bgm.tv/v0/search/subjects"
BANGUMI_ANIME_TYPE = 2
BANGUMI_USER_AGENT = "anime-qb-smart-downloader/0.1"
ALIAS_INFOBOX_KEYS = {
    "别名",
    "中文名",
    "英文名",
    "日文名",
    "原名",
    "罗马字",
    "罗马音",
}


@dataclass(slots=True)
class BangumiTitleMetadata:
    subject_id: int | None
    name: str | None
    name_cn: str | None
    aliases: list[str] = field(default_factory=list)
    date: str | None = None
    rank: int | None = None
    score: float | None = None

    @property
    def canonical(self) -> str:
        return self.name or self.name_cn or (self.aliases[0] if self.aliases else "")


def search_bangumi_titles(
    query: str,
    *,
    timeout_seconds: int = 8,
    max_results: int = 5,
    session: requests.Session | None = None,
) -> list[BangumiTitleMetadata]:
    if not query.strip():
        return []

    own_session = session is None
    http = session or requests.Session()
    try:
        response = http.post(
            f"{BANGUMI_SEARCH_ENDPOINT}?limit={max(1, max_results)}",
            json={
                "keyword": query,
                "sort": "match",
                "filter": {"type": [BANGUMI_ANIME_TYPE]},
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": BANGUMI_USER_AGENT,
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return []
    finally:
        if own_session:
            http.close()

    return parse_bangumi_search_response(payload)


def parse_bangumi_search_response(payload: dict[str, Any]) -> list[BangumiTitleMetadata]:
    subjects = payload.get("data") or []
    if not isinstance(subjects, list):
        return []

    results: list[BangumiTitleMetadata] = []
    for subject in subjects:
        if not isinstance(subject, dict):
            continue

        name = _clean_optional_text(subject.get("name"))
        name_cn = _clean_optional_text(subject.get("name_cn"))
        aliases = _dedupe_non_empty(
            [
                value
                for value in [
                    name,
                    name_cn,
                    *_extract_infobox_aliases(subject.get("infobox")),
                ]
                if value
            ]
        )
        if not aliases:
            continue

        results.append(
            BangumiTitleMetadata(
                subject_id=_coerce_int(subject.get("id")),
                name=name,
                name_cn=name_cn,
                aliases=aliases,
                date=_clean_optional_text(subject.get("date")),
                rank=_coerce_int(subject.get("rank")),
                score=_coerce_float((subject.get("rating") or {}).get("score")),
            )
        )

    return results


def _extract_infobox_aliases(infobox: Any) -> list[str]:
    if not isinstance(infobox, list):
        return []

    aliases: list[str] = []
    for item in infobox:
        if not isinstance(item, dict):
            continue
        key = _clean_optional_text(item.get("key")) or ""
        if not _is_alias_key(key):
            continue
        aliases.extend(_flatten_infobox_value(item.get("value")))
    return _dedupe_non_empty(aliases)


def _is_alias_key(key: str) -> bool:
    normalized = key.strip()
    return normalized in ALIAS_INFOBOX_KEYS or "别名" in normalized


def _flatten_infobox_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        flattened: list[str] = []
        for nested_key in ("v", "value", "name"):
            if nested_key in value:
                flattened.extend(_flatten_infobox_value(value.get(nested_key)))
        return flattened
    if isinstance(value, list):
        flattened: list[str] = []
        for item in value:
            flattened.extend(_flatten_infobox_value(item))
        return flattened
    return [str(value)]


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


def _clean_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
