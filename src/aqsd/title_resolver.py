from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from aqsd.utils import normalize_text


class TitleAliasGroup(Protocol):
    canonical: str
    aliases: list[str]


@dataclass(slots=True)
class TitleResolution:
    canonical: str
    expanded_queries: list[str]


def resolve_title_query(query: str, alias_groups: Iterable[TitleAliasGroup]) -> TitleResolution:
    normalized_query = normalize_title_key(query)
    if not normalized_query:
        return TitleResolution(canonical=query, expanded_queries=[query])

    for group in alias_groups:
        values = _group_values(group)
        if any(normalize_title_key(value) == normalized_query for value in values):
            return TitleResolution(
                canonical=group.canonical,
                expanded_queries=_dedupe_non_empty(values),
            )

    return TitleResolution(canonical=query, expanded_queries=[query])


def normalize_title_key(value: str) -> str:
    return normalize_text(value)


def _group_values(group: TitleAliasGroup) -> list[str]:
    return [group.canonical, *group.aliases]


def _dedupe_non_empty(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = normalize_title_key(value)
        if not value or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result
