from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from loguru import logger

from aqsd.anilist import TitleMetadata, fetch_anilist_title_metadata
from aqsd.utils import normalize_text


ANILIST_CACHE_SOURCE = "anilist-v3"


class TitleAliasGroup(Protocol):
    canonical: str
    aliases: list[str]


class MetadataCache(Protocol):
    def get_title_alias_cache(self, query: str, source: str) -> list[str] | None:
        ...

    def save_title_alias_cache(self, query: str, aliases: list[str], source: str, ttl_days: int) -> None:
        ...

    def delete_title_alias_cache(self, query: str, source: str) -> None:
        ...


class AniListSettings(Protocol):
    enabled: bool
    endpoint: str
    timeout_seconds: int
    cache_enabled: bool
    cache_ttl_days: int


@dataclass(slots=True)
class TitleAliasResult:
    canonical: str
    aliases: list[str]
    source: str
    confidence: float | None = None
    year: int | None = None


@dataclass(slots=True)
class TitleResolution:
    canonical: str
    expanded_queries: list[str]
    source: str = "query"
    year: int | None = None
    local_alias_matched: bool = False
    cache_hit: bool = False
    anilist_enabled: bool = False
    anilist_attempted: bool = False


def resolve_title_query(
    query: str,
    alias_groups: Iterable[TitleAliasGroup],
    *,
    anilist_settings: AniListSettings | None = None,
    cache: MetadataCache | None = None,
) -> TitleResolution:
    anilist_enabled = bool(anilist_settings is not None and anilist_settings.enabled)
    normalized_query = normalize_title_key(query)
    if not normalized_query:
        return TitleResolution(canonical=query, expanded_queries=[query], anilist_enabled=anilist_enabled)

    for group in alias_groups:
        values = _group_values(group)
        if any(normalize_title_key(value) == normalized_query for value in values):
            return TitleResolution(
                canonical=group.canonical,
                expanded_queries=_dedupe_non_empty(values),
                source="local",
                local_alias_matched=True,
                anilist_enabled=anilist_enabled,
            )

    if anilist_enabled:
        cache_query = normalized_query
        if cache is not None and anilist_settings is not None and anilist_settings.cache_enabled:
            cached_aliases = cache.get_title_alias_cache(cache_query, ANILIST_CACHE_SOURCE)
            if cached_aliases:
                aliases = _dedupe_non_empty([query, *cached_aliases])
                if _is_incomplete_alias_set(query, aliases):
                    logger.info("Ignoring incomplete AniList cache: query={}", query)
                    cache.delete_title_alias_cache(cache_query, ANILIST_CACHE_SOURCE)
                else:
                    return TitleResolution(
                        canonical=aliases[0],
                        expanded_queries=aliases,
                        source="anilist-cache",
                        cache_hit=True,
                        anilist_enabled=True,
                    )

        try:
            metadata_results = fetch_anilist_title_metadata(query, anilist_settings)
        except Exception as exc:
            logger.warning("AniList title metadata lookup failed: query={} error={}", query, exc)
        else:
            if metadata_results:
                best = _select_best_metadata_result(query, metadata_results)
                aliases = _dedupe_non_empty([query, *_search_aliases(best)])
                if cache is not None and anilist_settings.cache_enabled:
                    cache.save_title_alias_cache(
                        cache_query,
                        aliases,
                        ANILIST_CACHE_SOURCE,
                        anilist_settings.cache_ttl_days,
                    )
                return TitleResolution(
                    canonical=best.canonical,
                    expanded_queries=aliases,
                    source="anilist",
                    year=best.year,
                    anilist_enabled=True,
                    anilist_attempted=True,
                )

    return TitleResolution(
        canonical=query,
        expanded_queries=[query],
        source="query",
        anilist_enabled=anilist_enabled,
        anilist_attempted=anilist_enabled,
    )


def normalize_title_key(value: str) -> str:
    return normalize_text(value)


def _group_values(group: TitleAliasGroup) -> list[str]:
    return [group.canonical, *group.aliases]


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


def _search_aliases(metadata: TitleMetadata) -> list[str]:
    return _dedupe_non_empty(
        value
        for value in [
            metadata.canonical,
            metadata.romaji,
            metadata.english,
            metadata.native,
            *metadata.aliases,
        ]
        if value
    )


def _select_best_metadata_result(query: str, metadata_results: list[TitleMetadata]) -> TitleMetadata:
    return max(
        metadata_results,
        key=lambda item: (_score_metadata_result(query, item), -len(normalize_title_key(item.canonical))),
    )


def _score_metadata_result(query: str, metadata: TitleMetadata) -> int:
    normalized_query = normalize_title_key(query)
    official_titles = [value for value in [metadata.canonical, metadata.romaji, metadata.english, metadata.native] if value]
    score = 0

    exact_official = any(normalize_title_key(value) == normalized_query for value in official_titles)
    exact_alias = any(normalize_title_key(value) == normalized_query for value in metadata.aliases)
    if exact_official:
        score += 300
    elif exact_alias:
        score += 180

    for value in official_titles:
        normalized_value = normalize_title_key(value)
        if not normalized_value:
            continue
        if normalized_query in normalized_value or normalized_value in normalized_query:
            score += max(0, 120 - abs(len(normalized_value) - len(normalized_query)))

    if metadata.format == "TV":
        score += 10

    return score


def _is_incomplete_alias_set(query: str, aliases: list[str]) -> bool:
    normalized_query = normalize_title_key(query)
    normalized_aliases = {normalize_title_key(alias) for alias in aliases if normalize_title_key(alias)}
    if not normalized_aliases:
        return True
    return normalized_aliases == {normalized_query}
