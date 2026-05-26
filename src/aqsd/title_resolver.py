from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Iterable, Protocol

from loguru import logger

from aqsd.anilist import TitleMetadata, fetch_anilist_title_metadata
from aqsd.bangumi import BangumiTitleMetadata, search_bangumi_titles
from aqsd.models import ExpandedQueryDetail, ResolvedSubject
from aqsd.utils import normalize_text, tokenize_ascii_words


ANILIST_CACHE_SOURCE = "anilist-v3"
BANGUMI_CACHE_SOURCE = "bangumi-v2"
BANGUMI_CACHE_TTL_DAYS = 30
MAX_EXPANDED_QUERIES = 12
BANGUMI_HIGH_CONFIDENCE_THRESHOLD = 0.70
BANGUMI_MEDIUM_CONFIDENCE_THRESHOLD = 0.50
BANGUMI_MIN_MARGIN_TO_NEXT_UNRELATED = 0.20
BANGUMI_AMBIGUOUS_MARGIN = 0.10
ORIGINAL_QUERY_CONFIDENCE = 1.0
TITLE_CACHE_SCHEMA_VERSION = 3
ASCII_ROMAJI_HINTS = {
    "no",
    "wa",
    "ni",
    "de",
    "desu",
    "ore",
    "yuusha",
    "isekai",
    "tensei",
    "boushi",
    "tongari",
    "yoeru",
    "yuri",
    "hana",
    "kamiina",
    "nani",
}
GENERIC_CJK_TOKENS = {"的", "之", "与", "和", "魔法", "异世界", "工房", "少女", "女神", "勇者", "百合"}
GENERIC_ASCII_TOKENS = {"the", "of", "and", "a", "an", "atelier", "song", "uta"}


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

    def get_title_metadata_cache(self, query: str, source: str) -> Any:
        ...

    def save_title_metadata_cache(self, query: str, payload: Any, source: str, ttl_days: int) -> None:
        ...


class AniListSettings(Protocol):
    enabled: bool
    endpoint: str
    timeout_seconds: int
    cache_enabled: bool
    cache_ttl_days: int


class BangumiSettings(Protocol):
    enabled: bool
    timeout_seconds: int
    max_results: int


@dataclass(slots=True)
class TitleResolution:
    canonical: str
    expanded_queries: list[str]
    expanded_query_details: list[ExpandedQueryDetail] = field(default_factory=list)
    resolution_status: str = "unresolved"
    needs_review: bool = False
    source: str = "query"
    sources: list[str] = field(default_factory=list)
    year: int | None = None
    resolved_subject: ResolvedSubject | None = None
    candidate_subjects: list[dict[str, object]] = field(default_factory=list)
    rejected_subjects: list[dict[str, object]] = field(default_factory=list)
    local_alias_matched: bool = False
    cache_hit: bool = False
    bangumi_enabled: bool = False
    bangumi_attempted: bool = False
    anilist_enabled: bool = False
    anilist_attempted: bool = False


@dataclass(slots=True)
class _BangumiRankedSubject:
    metadata: BangumiTitleMetadata
    score: float
    reason: str


@dataclass(slots=True)
class _ProviderResolution:
    used: bool
    aliases: list[str] = field(default_factory=list)
    query_details: list[ExpandedQueryDetail] = field(default_factory=list)
    resolution_status: str = "unresolved"
    needs_review: bool = False
    canonical: str | None = None
    source: str = "query"
    sources: list[str] = field(default_factory=list)
    year: int | None = None
    resolved_subject: ResolvedSubject | None = None
    candidate_subjects: list[dict[str, object]] = field(default_factory=list)
    rejected_subjects: list[dict[str, object]] = field(default_factory=list)
    cache_hit: bool = False


def resolve_title_query(
    query: str,
    alias_groups: Iterable[TitleAliasGroup],
    *,
    bangumi_settings: BangumiSettings | None = None,
    anilist_settings: AniListSettings | None = None,
    cache: MetadataCache | None = None,
) -> TitleResolution:
    bangumi_enabled = bool(bangumi_settings is not None and bangumi_settings.enabled)
    anilist_enabled = bool(anilist_settings is not None and anilist_settings.enabled)
    normalized_query = normalize_title_key(query)
    if not normalized_query:
        details = [_build_original_query_detail(query)]
        return TitleResolution(
            canonical=query,
            expanded_queries=[query],
            expanded_query_details=details,
            resolution_status="unresolved",
            bangumi_enabled=bangumi_enabled,
            anilist_enabled=anilist_enabled,
        )

    for group in alias_groups:
        values = _group_values(group)
        if any(normalize_title_key(value) == normalized_query for value in values):
            details = _build_local_query_details(query, group)
            return TitleResolution(
                canonical=group.canonical,
                expanded_queries=_project_expanded_queries(details),
                expanded_query_details=details,
                resolution_status="resolved_high_confidence",
                source="local",
                sources=["local_aliases"],
                local_alias_matched=True,
                resolved_subject=ResolvedSubject(
                    source="local",
                    subject_id=group.canonical,
                    canonical=group.canonical,
                    confidence=0.99,
                    confidence_level="high",
                    reason="local title alias",
                ),
                bangumi_enabled=bangumi_enabled,
                anilist_enabled=anilist_enabled,
            )

    query_details = [_build_original_query_detail(query)]
    resolution_status = "unresolved"
    needs_review = False
    sources: list[str] = []
    canonical = query
    year: int | None = None
    cache_hit = False
    primary_source = "query"
    resolved_subject: ResolvedSubject | None = None
    candidate_subjects: list[dict[str, object]] = []
    rejected_subjects: list[dict[str, object]] = []
    provider_order = ["bangumi", "anilist"] if _should_prefer_bangumi_first(query) else ["anilist", "bangumi"]
    locked_by_ambiguity = False

    for provider in provider_order:
        if locked_by_ambiguity:
            break
        if provider == "bangumi" and bangumi_enabled and bangumi_settings is not None:
            bangumi_result = _resolve_with_bangumi(query, bangumi_settings, cache=cache)
            candidate_subjects = _prefer_candidate_subjects(candidate_subjects, bangumi_result.candidate_subjects)
            rejected_subjects.extend(bangumi_result.rejected_subjects)
            if bangumi_result.resolution_status == "ambiguous":
                resolution_status = "ambiguous"
                needs_review = True
                locked_by_ambiguity = True
                continue
            if bangumi_result.used:
                if primary_source == "query":
                    primary_source = bangumi_result.source
                    canonical = bangumi_result.canonical or canonical
                    resolved_subject = bangumi_result.resolved_subject or resolved_subject
                    resolution_status = bangumi_result.resolution_status or resolution_status
                    needs_review = bangumi_result.needs_review
                sources.extend(bangumi_result.sources)
                query_details = _merge_query_details(query_details, bangumi_result.query_details)
                cache_hit = cache_hit or bangumi_result.cache_hit
        if provider == "anilist" and anilist_enabled and anilist_settings is not None:
            anilist_result = _resolve_with_anilist(query, anilist_settings, cache=cache)
            if anilist_result.used:
                if primary_source == "query":
                    primary_source = anilist_result.source
                    canonical = anilist_result.canonical or canonical
                    year = anilist_result.year
                    resolved_subject = anilist_result.resolved_subject or resolved_subject
                    resolution_status = anilist_result.resolution_status or resolution_status
                    needs_review = anilist_result.needs_review
                elif year is None and anilist_result.year is not None:
                    year = anilist_result.year
                sources.extend(anilist_result.sources)
                query_details = _merge_query_details(query_details, anilist_result.query_details)
                cache_hit = cache_hit or anilist_result.cache_hit

    clean_details = query_details[:MAX_EXPANDED_QUERIES]
    if resolution_status in {"ambiguous", "unresolved"}:
        clean_details = [_build_original_query_detail(query)]
        canonical = query
        resolved_subject = None
    return TitleResolution(
        canonical=canonical,
        expanded_queries=_project_expanded_queries(clean_details),
        expanded_query_details=clean_details,
        resolution_status=resolution_status,
        needs_review=needs_review,
        source=primary_source,
        sources=_dedupe_non_empty(sources),
        year=year,
        resolved_subject=resolved_subject,
        candidate_subjects=candidate_subjects[:8],
        rejected_subjects=rejected_subjects[:8],
        cache_hit=cache_hit,
        bangumi_enabled=bangumi_enabled,
        bangumi_attempted=bangumi_enabled,
        anilist_enabled=anilist_enabled,
        anilist_attempted=anilist_enabled,
    )


def normalize_title_key(value: str) -> str:
    return normalize_text(value)


def contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" or "\u3040" <= char <= "\u30ff" for char in value)


def _should_prefer_bangumi_first(query: str) -> bool:
    if contains_cjk(query):
        return True
    normalized = normalize_title_key(query)
    ascii_tokens = tokenize_ascii_words(query)
    if len(normalized) <= 2:
        return True
    if len(ascii_tokens) <= 1 and normalized in {"fate", "gundam", "pokemon", "lovelive", "ll", "monogatari", "k"}:
        return True
    return False


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


def _prefer_candidate_subjects(
    existing: list[dict[str, object]],
    additions: list[dict[str, object]],
) -> list[dict[str, object]]:
    return additions if additions else existing


def _build_original_query_detail(query: str) -> ExpandedQueryDetail:
    language = _guess_query_language(query)
    return ExpandedQueryDetail(
        text=query,
        source="original",
        confidence=ORIGINAL_QUERY_CONFIDENCE,
        language=language,
        subject_confidence=None,
        alias_confidence=ORIGINAL_QUERY_CONFIDENCE,
        reason="original user query",
        search_eligible=bool(query.strip()),
        search_role="secondary",
        search_tier="secondary",
    )


def _build_local_query_details(query: str, group: TitleAliasGroup) -> list[ExpandedQueryDetail]:
    details: list[ExpandedQueryDetail] = []
    for value in _group_values(group):
        confidence = 0.98 if normalize_title_key(value) == normalize_title_key(group.canonical) else 0.92
        language = _guess_query_language(value)
        details.append(
            ExpandedQueryDetail(
                text=value,
                source="local",
                confidence=confidence,
                subject_id=group.canonical,
                language=language,
                subject_confidence=0.99,
                alias_confidence=confidence,
                reason="local title alias",
                search_eligible=_is_search_eligible_alias(
                    value,
                    query,
                    confidence,
                    subject_titles=_group_values(group),
                    language=language,
                    is_official=value == group.canonical,
                ),
                search_role="primary" if confidence >= 0.95 else "secondary",
                search_tier="primary" if confidence >= 0.95 else "secondary",
            )
        )
    return _merge_query_details([], details)


def _search_aliases(metadata: TitleMetadata) -> list[str]:
    return _dedupe_non_empty(
        value
        for value in [metadata.canonical, metadata.romaji, metadata.english, metadata.native, *metadata.aliases]
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
        if normalized_value and (normalized_query in normalized_value or normalized_value in normalized_query):
            score += max(0, 120 - abs(len(normalized_value) - len(normalized_query)))
    if metadata.format == "TV":
        score += 10
    return score


def _merge_query_details(existing: list[ExpandedQueryDetail], additions: list[ExpandedQueryDetail]) -> list[ExpandedQueryDetail]:
    merged: list[ExpandedQueryDetail] = []
    index_by_key: dict[str, int] = {}
    for detail in [*existing, *additions]:
        stripped = detail.text.strip()
        if not stripped:
            continue
        key = stripped.casefold()
        normalized_detail = ExpandedQueryDetail(
            text=stripped,
            source=detail.source,
            confidence=detail.confidence,
            subject_id=detail.subject_id,
            language=detail.language,
            subject_confidence=detail.subject_confidence,
            alias_confidence=detail.alias_confidence,
            reason=detail.reason,
            search_eligible=detail.search_eligible,
            search_role=detail.search_role,
            search_tier=detail.search_tier,
        )
        if key not in index_by_key:
            index_by_key[key] = len(merged)
            merged.append(normalized_detail)
            continue
        current = merged[index_by_key[key]]
        if normalized_detail.confidence > current.confidence:
            merged[index_by_key[key]] = normalized_detail
        else:
            current.search_eligible = current.search_eligible or normalized_detail.search_eligible
            current.alias_confidence = max(current.alias_confidence or 0.0, normalized_detail.alias_confidence or 0.0)
            current.subject_confidence = max(current.subject_confidence or 0.0, normalized_detail.subject_confidence or 0.0)
            if current.reason is None:
                current.reason = normalized_detail.reason
    return merged[:MAX_EXPANDED_QUERIES]


def _project_expanded_queries(details: list[ExpandedQueryDetail]) -> list[str]:
    return [detail.text for detail in details if detail.search_eligible][:MAX_EXPANDED_QUERIES]


def _is_incomplete_alias_set(query: str, aliases: list[str]) -> bool:
    normalized_query = normalize_title_key(query)
    normalized_aliases = {normalize_title_key(alias) for alias in aliases if normalize_title_key(alias)}
    return not normalized_aliases or normalized_aliases == {normalized_query}


def _resolve_with_bangumi(query: str, settings: BangumiSettings, *, cache: MetadataCache | None) -> _ProviderResolution:
    cache_query = normalize_title_key(query)
    if cache is not None:
        cached_payload = cache.get_title_metadata_cache(cache_query, BANGUMI_CACHE_SOURCE)
        cached_resolution = _load_bangumi_structured_cache(query, cached_payload)
        if cached_resolution is not None:
            return cached_resolution
        cached_aliases = cache.get_title_alias_cache(cache_query, BANGUMI_CACHE_SOURCE)
        if cached_aliases is not None:
            logger.info("Ignoring legacy Bangumi alias cache: query={}", query)
            cache.delete_title_alias_cache(cache_query, BANGUMI_CACHE_SOURCE)

    metadata_results = search_bangumi_titles(
        query,
        timeout_seconds=settings.timeout_seconds,
        max_results=settings.max_results,
    )
    if not metadata_results:
        return _ProviderResolution(used=False)

    ranked = _rank_bangumi_subjects(query, metadata_results)
    candidate_subjects = [_build_ranked_subject_debug_payload(item) for item in ranked[:8]]
    selected, resolution_status = _select_ranked_bangumi_subject(query, ranked)
    rejected_subjects = candidate_subjects if resolution_status in {"ambiguous", "unresolved"} else candidate_subjects[1:]
    if selected is None:
        return _ProviderResolution(
            used=False,
            resolution_status=resolution_status,
            needs_review=resolution_status == "ambiguous",
            candidate_subjects=candidate_subjects,
            rejected_subjects=rejected_subjects[:8],
        )

    details = _build_bangumi_query_details(query, selected.metadata, selected.score)
    aliases = _project_expanded_queries(details)
    resolved_subject = ResolvedSubject(
        source="bangumi",
        subject_id=selected.metadata.subject_id,
        canonical=selected.metadata.canonical or query,
        confidence=selected.score,
        confidence_level="high" if resolution_status == "resolved_high_confidence" else "medium",
        reason=selected.reason,
    )
    if cache is not None and not _is_incomplete_alias_set(query, aliases):
        cache.save_title_metadata_cache(
            cache_query,
            _build_bangumi_cache_payload(query, resolved_subject, details, candidate_subjects, rejected_subjects, resolution_status),
            BANGUMI_CACHE_SOURCE,
            BANGUMI_CACHE_TTL_DAYS,
        )
    return _ProviderResolution(
        used=True,
        aliases=aliases,
        query_details=details,
        resolution_status=resolution_status,
        canonical=selected.metadata.canonical or query,
        source="bangumi",
        sources=["bangumi"],
        resolved_subject=resolved_subject,
        candidate_subjects=candidate_subjects,
        rejected_subjects=rejected_subjects[:8],
    )


def _resolve_with_anilist(query: str, settings: AniListSettings, *, cache: MetadataCache | None) -> _ProviderResolution:
    cache_query = normalize_title_key(query)
    if cache is not None and settings.cache_enabled:
        cached_aliases = cache.get_title_alias_cache(cache_query, ANILIST_CACHE_SOURCE)
        if cached_aliases:
            aliases = _dedupe_non_empty([query, *cached_aliases])
            if _is_incomplete_alias_set(query, aliases):
                logger.info("Ignoring incomplete AniList cache: query={}", query)
                cache.delete_title_alias_cache(cache_query, ANILIST_CACHE_SOURCE)
            else:
                details = _build_cached_query_details(query, aliases, source="anilist-cache")
                return _ProviderResolution(
                    used=True,
                    aliases=_project_expanded_queries(details),
                    query_details=details,
                    resolution_status="resolved_medium_confidence",
                    canonical=aliases[1] if len(aliases) > 1 else aliases[0],
                    source="anilist-cache",
                    sources=["cache", "anilist"],
                    cache_hit=True,
                )

    try:
        metadata_results = fetch_anilist_title_metadata(query, settings)
    except Exception as exc:
        logger.warning("AniList title metadata lookup failed: query={} error={}", query, exc)
        return _ProviderResolution(used=False)

    if not metadata_results:
        return _ProviderResolution(used=False)

    best = _select_best_metadata_result(query, metadata_results)
    details = _build_anilist_query_details(query, best)
    aliases = _project_expanded_queries(details)
    if cache is not None and settings.cache_enabled:
        cache.save_title_alias_cache(cache_query, aliases, ANILIST_CACHE_SOURCE, settings.cache_ttl_days)
    resolved_subject = ResolvedSubject(
        source="anilist",
        subject_id=getattr(best, "id", None),
        canonical=best.canonical,
        confidence=min(0.95, max(0.60, _score_metadata_result(query, best) / 320)),
        confidence_level="medium",
        reason="selected_best_metadata_result",
    )
    return _ProviderResolution(
        used=True,
        aliases=aliases,
        query_details=details,
        resolution_status="resolved_medium_confidence",
        canonical=best.canonical,
        source="anilist",
        sources=["anilist"],
        year=best.year,
        resolved_subject=resolved_subject,
    )


def _load_bangumi_structured_cache(query: str, payload: Any) -> _ProviderResolution | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != TITLE_CACHE_SCHEMA_VERSION:
        return None
    cached_query = str(payload.get("query") or "").strip()
    if normalize_title_key(cached_query) != normalize_title_key(query):
        return None
    details_payload = payload.get("expanded_query_details")
    if not isinstance(details_payload, list):
        return None
    details = [_deserialize_expanded_query_detail(item, source_override="bangumi-cache") for item in details_payload if isinstance(item, dict)]
    details = [item for item in details if item is not None]
    if not details:
        return None
    aliases = _project_expanded_queries(details)
    if _is_incomplete_alias_set(query, aliases):
        return None
    subject_payload = payload.get("resolved_subject")
    resolved_subject = None
    canonical = query
    resolution_status = str(payload.get("resolution_status") or "resolved_medium_confidence")
    if isinstance(subject_payload, dict):
        canonical = str(subject_payload.get("canonical") or canonical)
        resolved_subject = ResolvedSubject(
            source="bangumi-cache",
            subject_id=subject_payload.get("subject_id"),
            canonical=canonical,
            confidence=float(subject_payload.get("confidence") or 0.0),
            confidence_level=subject_payload.get("confidence_level"),
            reason=str(subject_payload.get("reason") or "cached resolved subject"),
        )
    return _ProviderResolution(
        used=True,
        aliases=aliases,
        query_details=details,
        resolution_status=resolution_status,
        canonical=canonical,
        source="bangumi-cache",
        sources=["cache", "bangumi"],
        resolved_subject=resolved_subject,
        candidate_subjects=list(payload.get("candidate_subjects") or []),
        rejected_subjects=list(payload.get("rejected_subjects") or []),
        cache_hit=True,
    )


def _build_bangumi_cache_payload(
    query: str,
    resolved_subject: ResolvedSubject,
    details: list[ExpandedQueryDetail],
    candidate_subjects: list[dict[str, object]],
    rejected_subjects: list[dict[str, object]],
    resolution_status: str,
) -> dict[str, Any]:
    return {
        "schema_version": TITLE_CACHE_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "bangumi",
        "query": query,
        "resolution_status": resolution_status,
        "resolved_subject": asdict(resolved_subject),
        "expanded_query_details": [asdict(detail) for detail in details],
        "candidate_subjects": candidate_subjects[:8],
        "rejected_subjects": rejected_subjects[:8],
    }


def _deserialize_expanded_query_detail(payload: dict[str, Any], *, source_override: str | None = None) -> ExpandedQueryDetail | None:
    text = str(payload.get("text") or "").strip()
    if not text:
        return None
    search_tier = str(payload.get("search_tier") or payload.get("search_role") or "secondary")
    return ExpandedQueryDetail(
        text=text,
        source=source_override or str(payload.get("source") or "bangumi"),
        confidence=float(payload.get("confidence") or payload.get("alias_confidence") or 0.0),
        subject_id=payload.get("subject_id"),
        language=str(payload.get("language") or "unknown"),
        subject_confidence=float(payload["subject_confidence"]) if payload.get("subject_confidence") is not None else None,
        alias_confidence=float(payload["alias_confidence"]) if payload.get("alias_confidence") is not None else float(payload.get("confidence") or 0.0),
        reason=str(payload.get("reason") or "cached title alias"),
        search_eligible=bool(payload.get("search_eligible")),
        search_role=search_tier,
        search_tier=search_tier,
    )


def _build_cached_query_details(query: str, aliases: list[str], *, source: str) -> list[ExpandedQueryDetail]:
    details = [_build_original_query_detail(query)]
    for alias in aliases:
        if normalize_title_key(alias) == normalize_title_key(query):
            continue
        language = _guess_query_language(alias)
        details.append(
            ExpandedQueryDetail(
                text=alias,
                source=source,
                confidence=0.55,
                language=language,
                subject_confidence=None,
                alias_confidence=0.55,
                reason="cached title alias",
                search_eligible=_is_search_eligible_alias(alias, query, 0.55, subject_titles=aliases, language=language),
                search_role="secondary",
                search_tier="secondary",
            )
        )
    return _merge_query_details([], details)


def _rank_bangumi_subjects(query: str, metadata_results: list[BangumiTitleMetadata]) -> list[_BangumiRankedSubject]:
    ranked = [_BangumiRankedSubject(metadata=item, score=_score_bangumi_subject(query, item), reason=_describe_bangumi_match(query, item)) for item in metadata_results]
    ranked.sort(key=lambda item: (item.score, -len(normalize_title_key(item.metadata.canonical))), reverse=True)
    return ranked


def _select_ranked_bangumi_subject(query: str, ranked: list[_BangumiRankedSubject]) -> tuple[_BangumiRankedSubject | None, str]:
    if not ranked:
        return None, "unresolved"
    top = ranked[0]
    if top.score >= BANGUMI_HIGH_CONFIDENCE_THRESHOLD:
        return top, "resolved_high_confidence"
    if top.score < BANGUMI_MEDIUM_CONFIDENCE_THRESHOLD:
        return None, "unresolved"
    next_unrelated = _next_unrelated_ranked_subject(top, ranked[1:])
    if _is_short_or_generic_query(query) or not _has_subject_match_evidence(query, top.metadata):
        if next_unrelated is not None and top.score - next_unrelated.score <= BANGUMI_AMBIGUOUS_MARGIN:
            return None, "ambiguous"
        return None, "unresolved"
    if next_unrelated is None:
        return top, "resolved_medium_confidence"
    margin = top.score - next_unrelated.score
    if margin >= BANGUMI_MIN_MARGIN_TO_NEXT_UNRELATED:
        return top, "resolved_medium_confidence"
    if margin <= BANGUMI_AMBIGUOUS_MARGIN:
        return None, "ambiguous"
    return None, "unresolved"


def _score_bangumi_subject(query: str, metadata: BangumiTitleMetadata) -> float:
    official_titles = [value for value in [metadata.name_cn, metadata.name] if value]
    alias_titles = [value for value in metadata.aliases if value and value not in official_titles]
    best_official = max((_variant_similarity(query, value) for value in official_titles), default=0.0)
    best_alias = max((_variant_similarity(query, value) for value in alias_titles), default=0.0)
    score = max(best_official, best_alias)
    normalized_query = normalize_title_key(query)
    if any(normalize_title_key(value) == normalized_query for value in official_titles):
        score += 0.18
    elif any(normalize_title_key(value) == normalized_query for value in alias_titles):
        score += 0.10
    if contains_cjk(query) and metadata.name_cn:
        name_cn_score = _variant_similarity(query, metadata.name_cn)
        score += 0.08 if name_cn_score >= 0.85 else 0.04 if name_cn_score >= 0.60 else 0.0
    if metadata.rank is not None and metadata.rank <= 500:
        score += 0.01
    if metadata.score is not None and metadata.score >= 7.5:
        score += 0.01
    return min(score, 1.0)


def _describe_bangumi_match(query: str, metadata: BangumiTitleMetadata) -> str:
    scores = {
        "name_cn": _variant_similarity(query, metadata.name_cn or ""),
        "name": _variant_similarity(query, metadata.name or ""),
        "alias": max((_variant_similarity(query, value) for value in metadata.aliases), default=0.0),
    }
    best_field = max(scores, key=scores.get)
    return f"best_{best_field}_similarity={scores[best_field]:.3f}"


def _build_ranked_subject_debug_payload(item: _BangumiRankedSubject) -> dict[str, object]:
    return {
        "source": "bangumi",
        "subject_id": item.metadata.subject_id,
        "canonical": item.metadata.canonical,
        "confidence": round(item.score, 3),
        "reason": item.reason,
    }


def _next_unrelated_ranked_subject(
    top: _BangumiRankedSubject,
    others: list[_BangumiRankedSubject],
) -> _BangumiRankedSubject | None:
    for other in others:
        if not _is_likely_same_franchise_or_sequel(top.metadata, other.metadata):
            return other
    return None


def _is_likely_same_franchise_or_sequel(
    top_subject: BangumiTitleMetadata,
    other_subject: BangumiTitleMetadata,
) -> bool:
    top_titles = _subject_title_variants(top_subject)
    other_titles = _subject_title_variants(other_subject)
    sequel_markers = (
        "season 2",
        "season 3",
        "2nd season",
        "3rd season",
        "part 2",
        "第2期",
        "第3期",
        "第二季",
        "第三季",
        "第2クール",
        "第3クール",
    )
    for top_title in top_titles:
        normalized_top = normalize_title_key(top_title)
        if not normalized_top:
            continue
        for other_title in other_titles:
            normalized_other = normalize_title_key(other_title)
            if not normalized_other:
                continue
            if normalized_top == normalized_other:
                return True
            if normalized_other.startswith(normalized_top):
                suffix = normalized_other[len(normalized_top) :].strip()
                if suffix and any(marker in suffix for marker in sequel_markers):
                    return True
            if normalized_top.startswith(normalized_other):
                suffix = normalized_top[len(normalized_other) :].strip()
                if suffix and any(marker in suffix for marker in sequel_markers):
                    return True
            if _variant_similarity(top_title, other_title) >= 0.88:
                return True
    return False


def _subject_title_variants(metadata: BangumiTitleMetadata) -> list[str]:
    return _dedupe_non_empty([metadata.name_cn or "", metadata.name or "", *metadata.aliases])


def _is_short_or_generic_query(query: str) -> bool:
    normalized = normalize_title_key(query)
    if not normalized:
        return True
    ascii_tokens = tokenize_ascii_words(query)
    if contains_cjk(query):
        return len(normalized) <= 2
    if len(ascii_tokens) <= 1 and len(normalized) <= 5:
        return True
    return normalized in {"fate", "gundam", "pokemon", "lovelive", "ll", "monogatari", "k"}


def _has_subject_match_evidence(query: str, metadata: BangumiTitleMetadata) -> bool:
    titles = _subject_title_variants(metadata)
    if any(_variant_similarity(query, title) >= 0.60 for title in titles):
        return True
    query_language = _guess_query_language(query)
    query_tokens = _extract_core_tokens(query, query_language)
    if not query_tokens:
        return False
    subject_tokens = set()
    for title in titles:
        subject_tokens.update(_extract_core_tokens(title, _guess_query_language(title)))
    return bool(query_tokens & subject_tokens)


def _variant_similarity(query: str, value: str) -> float:
    normalized_query = normalize_title_key(query)
    normalized_value = normalize_title_key(value)
    if not normalized_query or not normalized_value:
        return 0.0
    if normalized_query == normalized_value:
        return 1.0
    shorter = min(len(normalized_query), len(normalized_value))
    longer = max(len(normalized_query), len(normalized_value))
    coverage = shorter / longer if longer else 0.0
    if normalized_query in normalized_value or normalized_value in normalized_query:
        if shorter >= 4 and coverage >= 0.55:
            return min(0.96, 0.82 + coverage * 0.12)
        query_tokens = tokenize_ascii_words(query)
        value_tokens = tokenize_ascii_words(value)
        if len(query_tokens) == 1 and query_tokens[0] in set(value_tokens) and len(query_tokens[0]) >= 4:
            return max(0.56, 0.42 + coverage * 0.20)
        return max(0.30, 0.36 + coverage * 0.20)
    sequence_ratio = SequenceMatcher(None, normalized_query, normalized_value).ratio()
    query_tokens = tokenize_ascii_words(query)
    value_tokens = tokenize_ascii_words(value)
    if query_tokens and value_tokens:
        overlap = len(set(query_tokens) & set(value_tokens))
        token_ratio = overlap / max(len(set(query_tokens) | set(value_tokens)), 1)
        sequence_ratio = max(sequence_ratio, token_ratio)
        query_token_set = set(query_tokens)
        value_token_set = set(value_tokens)
        if len(query_token_set) == 1 and query_token_set.issubset(value_token_set):
            only_token = next(iter(query_token_set))
            if len(only_token) >= 4:
                sequence_ratio = max(sequence_ratio, 0.56)
    return sequence_ratio


def _build_bangumi_query_details(query: str, metadata: BangumiTitleMetadata, subject_confidence: float) -> list[ExpandedQueryDetail]:
    details = [_build_original_query_detail(query)]
    official_titles = _dedupe_non_empty([metadata.name_cn or "", metadata.name or ""])
    subject_titles = _dedupe_non_empty([metadata.name_cn or "", metadata.name or "", *metadata.aliases, query])
    for value in _dedupe_non_empty([metadata.name_cn or "", metadata.name or "", *metadata.aliases]):
        language, source_kind = _guess_bangumi_language(value, metadata)
        is_official = value in official_titles
        alias_confidence = _score_alias_confidence(
            value,
            original_query=query,
            subject_titles=subject_titles,
            language=language,
            is_official=is_official,
            source_kind=source_kind,
        )
        search_tier = _classify_search_tier(language, is_official, alias_confidence)
        search_eligible = _is_search_eligible_alias(
            value,
            query,
            alias_confidence,
            subject_titles=subject_titles,
            language=language,
            is_official=is_official,
            search_tier=search_tier,
        )
        details.append(
            ExpandedQueryDetail(
                text=value,
                source="bangumi",
                confidence=alias_confidence,
                subject_id=metadata.subject_id,
                language=language,
                subject_confidence=subject_confidence,
                alias_confidence=alias_confidence,
                reason=f"bangumi_{source_kind}",
                search_eligible=search_eligible,
                search_role=search_tier,
                search_tier=search_tier,
            )
        )
    return _merge_query_details([], details)


def _build_anilist_query_details(query: str, metadata: TitleMetadata) -> list[ExpandedQueryDetail]:
    details = [_build_original_query_detail(query)]
    ordered_values = _dedupe_non_empty([metadata.canonical, metadata.romaji or "", metadata.english or "", metadata.native or "", *metadata.aliases])
    subject_titles = ordered_values + [query]
    subject_confidence = min(0.95, max(0.60, _score_metadata_result(query, metadata) / 320))
    for value in ordered_values:
        language = _guess_anilist_language(value, metadata)
        is_official = value in {metadata.canonical, metadata.romaji or "", metadata.english or "", metadata.native or ""}
        alias_confidence = _score_alias_confidence(
            value,
            original_query=query,
            subject_titles=subject_titles,
            language=language,
            is_official=is_official,
            source_kind="anilist_official" if is_official else "anilist_alias",
        )
        search_tier = _classify_search_tier(language, is_official, alias_confidence)
        details.append(
            ExpandedQueryDetail(
                text=value,
                source="anilist",
                confidence=alias_confidence,
                subject_id=getattr(metadata, "id", None),
                language=language,
                subject_confidence=subject_confidence,
                alias_confidence=alias_confidence,
                reason="resolved AniList subject title" if is_official else "resolved AniList subject alias",
                search_eligible=_is_search_eligible_alias(
                    value,
                    query,
                    alias_confidence,
                    subject_titles=subject_titles,
                    language=language,
                    is_official=is_official,
                    search_tier=search_tier,
                ),
                search_role=search_tier,
                search_tier=search_tier,
            )
        )
    return _merge_query_details([], details)


def _score_alias_confidence(
    alias: str,
    *,
    original_query: str,
    subject_titles: list[str],
    language: str,
    is_official: bool,
    source_kind: str,
) -> float:
    normalized_alias = normalize_title_key(alias)
    if not normalized_alias:
        return 0.0
    best_subject_similarity = max((_variant_similarity(alias, title) for title in subject_titles if title), default=0.0)
    query_similarity = _variant_similarity(original_query, alias)
    confidence = max(best_subject_similarity * 0.55 + query_similarity * 0.45, query_similarity)
    if is_official:
        confidence = max(confidence, 0.88 if language in {"en", "romaji"} else 0.92)
    elif source_kind.endswith("official"):
        confidence = max(confidence, 0.84)
    if _looks_generic_alias(alias, language):
        confidence -= 0.28
    if _shares_core_signal(alias, subject_titles, original_query, language):
        confidence += 0.08
    if not _shares_core_signal(alias, subject_titles, original_query, language) and not is_official:
        confidence -= 0.18
    return max(0.0, min(confidence, 0.99))


def _classify_search_tier(language: str, is_official: bool, alias_confidence: float) -> str:
    if alias_confidence < 0.52:
        return "display_only"
    if is_official:
        return "primary"
    if language in {"en", "romaji", "ja"} and alias_confidence >= 0.75:
        return "primary"
    return "secondary"


def _is_search_eligible_alias(
    value: str,
    original_query: str,
    alias_confidence: float,
    *,
    subject_titles: list[str],
    language: str | None = None,
    is_official: bool = False,
    search_tier: str | None = None,
) -> bool:
    normalized_value = normalize_title_key(value)
    if not normalized_value:
        return False
    if normalize_title_key(original_query) == normalized_value:
        return True
    if search_tier == "display_only":
        return False
    min_len = 2 if language in {"zh", "ja"} else 3
    if len(normalized_value) < min_len and not is_official:
        return False
    if _looks_generic_alias(value, language or "unknown") and not is_official:
        return False
    if not _shares_core_signal(value, subject_titles, original_query, language or "unknown") and not is_official:
        return False
    if language in {"en", "romaji"}:
        return alias_confidence >= (0.55 if _shares_core_signal(value, subject_titles, original_query, language) else 0.72)
    return alias_confidence >= 0.62


def _shares_core_signal(alias: str, subject_titles: list[str], original_query: str, language: str) -> bool:
    normalized_alias = normalize_title_key(alias)
    if normalize_title_key(original_query) == normalized_alias:
        return True
    if any(_variant_similarity(alias, title) >= 0.62 for title in subject_titles if title):
        return True
    alias_tokens = _extract_core_tokens(alias, language)
    if not alias_tokens:
        return False
    subject_tokens = set()
    for title in [original_query, *subject_titles]:
        subject_tokens.update(_extract_core_tokens(title, _guess_query_language(title)))
    return bool(alias_tokens & subject_tokens)


def _extract_core_tokens(value: str, language: str) -> set[str]:
    if language in {"en", "romaji"}:
        return {token for token in tokenize_ascii_words(value) if len(token) >= 4 and token not in GENERIC_ASCII_TOKENS}
    normalized = value.strip()
    if not normalized:
        return set()
    chunks: set[str] = set()
    for index in range(len(normalized) - 1):
        token = normalized[index : index + 2]
        if token not in GENERIC_CJK_TOKENS:
            chunks.add(token)
    for index in range(len(normalized) - 2):
        token = normalized[index : index + 3]
        if token not in GENERIC_CJK_TOKENS:
            chunks.add(token)
    return chunks


def _looks_generic_alias(value: str, language: str) -> bool:
    if language in {"en", "romaji"}:
        tokens = tokenize_ascii_words(value)
        if len(tokens) <= 2 and any(token in {"song", "uta", "classman"} for token in tokens):
            return True
        filtered = [token for token in tokens if token not in GENERIC_ASCII_TOKENS]
        return len(filtered) <= 1 and len(tokens) <= 3
    return len(_extract_core_tokens(value, language)) <= 1 and len(value.strip()) <= 4


def _guess_query_language(value: str) -> str:
    if not value.strip():
        return "unknown"
    if any("\u3040" <= char <= "\u30ff" for char in value):
        return "ja"
    if contains_cjk(value):
        return "zh"
    tokens = tokenize_ascii_words(value)
    if not tokens:
        return "unknown"
    romaji_hits = sum(1 for token in tokens if token in ASCII_ROMAJI_HINTS)
    english_hits = sum(1 for token in tokens if token in {"the", "of", "with", "my", "hat", "witch", "atelier", "reincarnation", "appearance", "flower"})
    if romaji_hits >= 2 and romaji_hits >= english_hits:
        return "romaji"
    if english_hits >= 1:
        return "en"
    return "en" if any(token.endswith("tion") or token.endswith("ing") for token in tokens) else "romaji"


def _guess_bangumi_language(value: str, metadata: BangumiTitleMetadata) -> tuple[str, str]:
    if value == (metadata.name_cn or ""):
        return "zh", "name_cn"
    if value == (metadata.name or ""):
        if any("\u3040" <= char <= "\u30ff" for char in value):
            return "ja", "name"
        if contains_cjk(value):
            return "zh", "name"
    return _guess_query_language(value), "alias"


def _guess_anilist_language(value: str, metadata: TitleMetadata) -> str:
    if value == (metadata.native or ""):
        return "ja" if any("\u3040" <= char <= "\u30ff" for char in value) else "zh"
    if value == (metadata.english or ""):
        return "en"
    if value == (metadata.romaji or ""):
        return "romaji"
    return _guess_query_language(value)
