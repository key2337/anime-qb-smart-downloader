from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from aqsd.config import AppConfig
from aqsd.database import Database
from aqsd.matcher import match_candidate
from aqsd.models import AnimeRule, Candidate, ExpandedQueryDetail, SearchDiagnostics, TitleEvidence
from aqsd.parser import parse_candidate
from aqsd.rss import fetch_rss
from aqsd.scorer import score_candidate
from aqsd.utils import contains_any_search_keyword, contains_search_keyword, normalize_text


@dataclass(slots=True)
class DiscoveryResult:
    rss_entries_total: int = 0
    parsed_success_total: int = 0
    candidates: list[Candidate] = field(default_factory=list)
    diagnostics: SearchDiagnostics | None = None

    @property
    def matched_total(self) -> int:
        return len(self.candidates)


@dataclass(slots=True)
class SearchRequest:
    query: str
    expanded_queries: list[str] = field(default_factory=list)
    expanded_query_details: list[ExpandedQueryDetail] = field(default_factory=list)
    episodes: list[str] = field(default_factory=list)
    season: int | None = None
    resolution: str | None = None
    groups: list[str] = field(default_factory=list)
    subtitle_type: str | None = None
    raw_only: bool = False
    exclude_batch: bool = False
    release_mode: str = "any"
    min_seeders: int = 0
    limit: int | None = None


_DEFAULT_STAGE_COUNTS = {
    "count_after_fetch": 0,
    "count_after_title_match": 0,
    "count_after_season_filter": 0,
    "count_after_exclude_batch_filter": 0,
    "count_after_release_mode_filter": 0,
    "count_after_episode_filter": 0,
    "count_after_resolution_filter": 0,
    "count_after_group_filter": 0,
    "count_after_subtitle_filter": 0,
    "count_after_raw_only_filter": 0,
    "count_after_min_seeders_filter": 0,
    "count_after_dedupe": 0,
    "count_after_limit": 0,
}


def group_candidates_by_episode(candidates: list[Candidate]) -> dict[tuple[str, str], list[Candidate]]:
    grouped: dict[tuple[str, str], list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        if not candidate.anime_name or not candidate.episode:
            continue
        grouped[(candidate.anime_name, candidate.episode)].append(candidate)
    return grouped


def discover_rule_candidates(
    config: AppConfig,
    db: Database | None = None,
    *,
    skip_downloaded: bool = True,
    persist_candidates: bool = False,
) -> DiscoveryResult:
    rules = config.anime_rules
    rule_by_name = {rule.name: rule for rule in rules}
    default_category = config.qb.default_category
    default_save_path = config.qb.default_save_path
    result = DiscoveryResult()
    seen_urls: set[str] = set()

    for source in config.rss_sources:
        if not source.enabled:
            continue

        logger.info("Fetching RSS: {}", source.name)
        items = fetch_rss(source)
        result.rss_entries_total += len(items)

        for item in items:
            if not item.url or item.url in seen_urls:
                continue

            seen_urls.add(item.url)
            candidate = parse_candidate(item)
            if candidate.episode is not None:
                result.parsed_success_total += 1

            matched = match_candidate(
                candidate,
                rules,
                config.profiles,
                default_category,
                default_save_path,
            )
            if not matched or not matched.anime_name or not matched.episode:
                continue

            if skip_downloaded and db and db.already_downloaded(matched.anime_name, matched.episode):
                continue

            rule = rule_by_name[matched.matched_rule_name or ""]
            profile = config.profiles.get(rule.profile, {})
            score_candidate(matched, rule, profile)

            if persist_candidates and db:
                db.save_candidate(matched)

            result.candidates.append(matched)

    return result


def discover_search_candidates(config: AppConfig, request: SearchRequest) -> DiscoveryResult:
    result = DiscoveryResult()
    seen_urls: set[str] = set()
    seen_hashes: set[str] = set()
    seen_candidate_keys: set[tuple[object, ...]] = set()
    attempted_sources: list[str] = []

    if not request.expanded_queries:
        request.expanded_queries.append(request.query)
    if not request.expanded_query_details:
        request.expanded_query_details.append(
            ExpandedQueryDetail(text=request.query, source="original", confidence=1.0, alias_confidence=1.0, search_role="primary", search_tier="primary")
        )

    logger.info("Search query: {}", request.query)
    result.diagnostics = SearchDiagnostics(
        original_query=request.query,
        expanded_queries=list(request.expanded_queries),
        expanded_query_details=list(request.expanded_query_details),
        active_filters=_build_active_filters(request),
        stage_counts=dict(_DEFAULT_STAGE_COUNTS),
    )

    for source in config.rss_sources:
        if not source.enabled:
            continue

        if "RSS" not in attempted_sources:
            attempted_sources.append("RSS")

        rss_keywords = _rss_keywords(source, request)
        if rss_keywords:
            for keyword in rss_keywords:
                logger.info("Fetching RSS: {} keyword={}", source.name, keyword)
                items = fetch_rss(source, keyword=keyword)
                result.rss_entries_total += len(items)
                _collect_search_matches(
                    items,
                    request,
                    config,
                    result,
                    seen_urls,
                    seen_hashes,
                    seen_candidate_keys,
                )
        else:
            logger.info("Fetching RSS: {}", source.name)
            items = fetch_rss(source)
            result.rss_entries_total += len(items)
            _collect_search_matches(
                items,
                request,
                config,
                result,
                seen_urls,
                seen_hashes,
                seen_candidate_keys,
            )

    result.candidates = sorted(
        result.candidates,
        key=lambda item: (item.score, item.seeders, item.title),
        reverse=True,
    )
    candidate_count_after_filter = len(result.candidates)
    if request.limit is not None:
        result.candidates = result.candidates[: request.limit]
    if result.diagnostics is not None:
        result.diagnostics.sources = attempted_sources
        result.diagnostics.candidate_count_after_filter = candidate_count_after_filter
        result.diagnostics.stage_counts["count_after_limit"] = len(result.candidates)
        result.diagnostics.suggestions = _build_search_suggestions(result.diagnostics)

    return result


def _rss_keywords(source: Any, request: SearchRequest) -> list[str] | None:
    source_url = source.url if hasattr(source, "url") else source.get("url", "")
    if "dmhy.org" not in source_url:
        return None
    from urllib.parse import parse_qs, urlparse

    existing_params = parse_qs(urlparse(source_url).query)
    if "keyword" in existing_params:
        return None
    queries = [detail.text for detail in (request.expanded_query_details or []) if detail.search_eligible]
    if not queries:
        queries = list(request.expanded_queries or [request.query])
    return queries[:1]


def _collect_search_matches(
    items: list[Candidate],
    request: SearchRequest,
    config: AppConfig,
    result: DiscoveryResult,
    seen_urls: set[str],
    seen_hashes: set[str],
    seen_candidate_keys: set[tuple[object, ...]],
) -> None:
    for item in items:
        if not item.url:
            continue

        candidate = parse_candidate(item)
        _increment_stage(result.diagnostics, "count_after_fetch")

        if candidate.episode is not None:
            result.parsed_success_total += 1

        matched_detail = _match_query_detail(candidate, request)
        if request.query and matched_detail is None:
            _increment_drop_reason(result.diagnostics, "title_match")
            continue
        if matched_detail is not None:
            _attach_match_evidence(candidate, matched_detail)
        _increment_stage(result.diagnostics, "count_after_title_match")

        drop_reason = _filter_candidate(candidate, request, result.diagnostics)
        if drop_reason is not None:
            _increment_drop_reason(result.diagnostics, drop_reason)
            continue

        if candidate.url in seen_urls:
            _increment_drop_reason(result.diagnostics, "duplicate_url")
            continue
        hash_key = _hash_key(candidate)
        if hash_key and hash_key in seen_hashes:
            _increment_drop_reason(result.diagnostics, "duplicate_info_hash")
            continue
        duplicate_key = _candidate_dedupe_key(candidate)
        if duplicate_key in seen_candidate_keys:
            _increment_drop_reason(result.diagnostics, "duplicate_candidate")
            continue

        seen_urls.add(candidate.url)
        if hash_key:
            seen_hashes.add(hash_key)
        seen_candidate_keys.add(duplicate_key)
        _increment_stage(result.diagnostics, "count_after_dedupe")

        _score_search_candidate(candidate, request, config)
        result.candidates.append(candidate)


def _candidate_dedupe_key(candidate: Candidate) -> tuple[object, ...]:
    return (
        normalize_text(candidate.title),
        normalize_text(candidate.parsed_title or ""),
        candidate.season or 0,
        candidate.episode or "",
        normalize_text(candidate.group or ""),
        (candidate.resolution or "").casefold(),
        bool(candidate.is_batch),
    )


def _hash_key(candidate: Candidate) -> str | None:
    if not candidate.info_hash:
        return None
    return candidate.info_hash.strip().casefold() or None


def _increment_stage(diagnostics: SearchDiagnostics | None, key: str) -> None:
    if diagnostics is None:
        return
    diagnostics.stage_counts[key] = diagnostics.stage_counts.get(key, 0) + 1
    if key == "count_after_title_match":
        diagnostics.candidate_count_before_filter = diagnostics.stage_counts[key]


def _increment_drop_reason(diagnostics: SearchDiagnostics | None, key: str) -> None:
    if diagnostics is None:
        return
    diagnostics.filter_drop_reasons[key] = diagnostics.filter_drop_reasons.get(key, 0) + 1


def _filter_candidate(
    candidate: Candidate,
    request: SearchRequest,
    diagnostics: SearchDiagnostics | None,
) -> str | None:
    if request.season is not None:
        actual_season = candidate.season if candidate.season is not None else 1
        if actual_season != request.season:
            return "season"
    _increment_stage(diagnostics, "count_after_season_filter")

    if request.exclude_batch and candidate.is_batch:
        return "exclude_batch"
    _increment_stage(diagnostics, "count_after_exclude_batch_filter")

    if request.release_mode == "episode" and candidate.is_batch:
        return "release_mode"

    if request.release_mode == "batch" and not candidate.is_batch:
        return "release_mode"
    _increment_stage(diagnostics, "count_after_release_mode_filter")

    if request.episodes and not _episode_matches_request(candidate, request):
        return "episode"
    _increment_stage(diagnostics, "count_after_episode_filter")

    if request.resolution and (candidate.resolution or "").casefold() != request.resolution.casefold():
        return "resolution"
    _increment_stage(diagnostics, "count_after_resolution_filter")

    if request.groups and not _value_in_normalized_set(candidate.group, request.groups):
        return "group"
    _increment_stage(diagnostics, "count_after_group_filter")

    if request.subtitle_type and (candidate.subtitle_type or "").casefold() != request.subtitle_type.casefold():
        return "subtitle"
    _increment_stage(diagnostics, "count_after_subtitle_filter")

    if request.raw_only and not candidate.is_raw:
        return "raw_only"
    _increment_stage(diagnostics, "count_after_raw_only_filter")

    if candidate.seeders < request.min_seeders:
        return "min_seeders"
    _increment_stage(diagnostics, "count_after_min_seeders_filter")

    return None


def _match_query_detail(candidate: Candidate, request: SearchRequest) -> ExpandedQueryDetail | None:
    searchable_value = candidate.parsed_title or candidate.title
    details = request.expanded_query_details or [
        ExpandedQueryDetail(text=value, source="original", confidence=1.0, alias_confidence=1.0, search_role="secondary", search_tier="secondary")
        for value in (request.expanded_queries or [request.query])
        if value
    ]
    matched = [detail for detail in details if detail.search_eligible and contains_search_keyword(searchable_value, detail.text)]
    if matched:
        matched.sort(key=lambda detail: (detail.confidence, len(normalize_text(detail.text))), reverse=True)
        return matched[0]
    if request.query and contains_any_search_keyword(searchable_value, [request.query]):
        return ExpandedQueryDetail(text=request.query, source="original", confidence=1.0, alias_confidence=1.0, search_role="secondary", search_tier="secondary")
    return None


def _attach_match_evidence(candidate: Candidate, detail: ExpandedQueryDetail) -> None:
    candidate.matched_query = detail.text
    candidate.matched_query_source = detail.source
    candidate.matched_query_subject_id = detail.subject_id
    candidate.matched_query_confidence = detail.confidence
    searchable_value = candidate.parsed_title or candidate.title
    exact = normalize_text(searchable_value) == normalize_text(detail.text)
    evidence_type = f"{detail.language}_{'exact' if exact else 'near'}_match"
    candidate.title_evidence = TitleEvidence(
        type=evidence_type,
        score=detail.confidence,
        reason=f"candidate title matched {detail.source} {detail.search_role} query",
    )


def _episode_matches_request(candidate: Candidate, request: SearchRequest) -> bool:
    normalized_episodes = _normalize_episode_values(request.episodes)
    if (candidate.episode or "") in normalized_episodes:
        return True

    if candidate.is_batch and request.release_mode == "batch":
        return True

    return False


def _score_search_candidate(candidate: Candidate, request: SearchRequest, config: AppConfig) -> None:
    rule = AnimeRule(
        name=request.query,
        prefer_groups=list(request.groups or []),
        save_path=config.qb.default_save_path,
        category=config.qb.default_category,
    )

    candidate.matched_rule_name = "__search__"
    candidate.anime_name = request.query
    candidate.category = config.qb.default_category
    candidate.save_path = config.qb.default_save_path
    score_candidate(
        candidate,
        rule,
        profile={},
        search_context={
            "query": request.query,
            "expanded_queries": request.expanded_queries,
            "expanded_query_details": request.expanded_query_details,
            "episodes": _normalize_episode_values(request.episodes),
            "resolution": request.resolution,
            "groups": request.groups,
            "subtitle_type": request.subtitle_type,
            "raw_only": request.raw_only,
            "exclude_batch": request.exclude_batch,
            "release_mode": request.release_mode,
            "min_seeders": request.min_seeders,
        },
    )


def _normalize_episode_values(values: list[str]) -> set[str]:
    normalized: set[str] = set()
    for value in values:
        stripped = value.strip()
        if not stripped:
            continue
        normalized.add(stripped)
        if stripped.isdigit():
            normalized.add(stripped.zfill(2))
    return normalized


def _value_in_normalized_set(value: str | None, candidates: list[str]) -> bool:
    if not value:
        return False
    normalized_value = normalize_text(value)
    return any(normalize_text(candidate) == normalized_value for candidate in candidates if candidate)


def _build_active_filters(request: SearchRequest) -> dict[str, object]:
    filters: dict[str, object] = {"release_mode": request.release_mode}
    if request.season is not None:
        filters["season"] = request.season
    if request.episodes:
        filters["episode"] = ", ".join(request.episodes)
    if request.resolution:
        filters["resolution"] = request.resolution
    if request.groups:
        filters["group"] = ", ".join(request.groups)
    if request.subtitle_type:
        filters["subtitle"] = request.subtitle_type
    if request.raw_only:
        filters["raw_only"] = True
    if request.exclude_batch:
        filters["exclude_batch"] = True
    if request.min_seeders > 0:
        filters["min_seeders"] = request.min_seeders
    if request.limit is not None:
        filters["limit"] = request.limit
    return filters


def _build_search_suggestions(diagnostics: SearchDiagnostics) -> list[str]:
    suggestions: list[str] = []
    expanded = diagnostics.expanded_queries or [diagnostics.original_query]
    if len(expanded) <= 1:
        suggestions.append("可尝试换一个别名或关键词重新搜索。")

    before_count = diagnostics.candidate_count_before_filter or 0
    after_count = diagnostics.candidate_count_after_filter or 0
    filtered_out = before_count > 0 and after_count == 0
    no_results = after_count == 0

    if "subtitle" in diagnostics.active_filters and no_results:
        suggestions.append("没有找到符合字幕条件的结果，可尝试改为“不限字幕”。")
    if "group" in diagnostics.active_filters and no_results:
        suggestions.append("可尝试去掉字幕组限制。")
    if "resolution" in diagnostics.active_filters:
        suggestions.append("可尝试放宽分辨率条件，例如改为 1080p、720p 或不限制。")
    if "episode" in diagnostics.active_filters and filtered_out:
        suggestions.append("可能是集数解析失败，可尝试清空集数后查看候选，或尝试合集 / 整季资源。")
    if diagnostics.active_filters.get("release_mode") not in (None, "any") and no_results:
        suggestions.append("可尝试改为不限资源类型。")
    if diagnostics.active_filters.get("release_mode") != "batch" and no_results:
        suggestions.append("也可尝试搜索合集 / 整季资源。")
    if "season" in diagnostics.active_filters and no_results:
        suggestions.append("可尝试去掉季度限制。")
    if "raw_only" in diagnostics.active_filters and no_results:
        suggestions.append("只看 RAW 可能过严，可先取消 RAW 限制。")

    deduped: list[str] = []
    for suggestion in suggestions:
        if suggestion not in deduped:
            deduped.append(suggestion)
    return deduped[:6]
