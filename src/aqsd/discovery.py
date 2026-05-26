from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from loguru import logger

from aqsd.config import AppConfig
from aqsd.database import Database
from aqsd.matcher import match_candidate
from aqsd.models import AnimeRule, Candidate, ExpandedQueryDetail, SearchDiagnostics, TitleEvidence
from aqsd.nyaa import fetch_nyaa_candidates
from aqsd.parser import parse_candidate
from aqsd.rss import fetch_rss
from aqsd.scorer import score_candidate
from aqsd.title_resolver import TitleResolution, resolve_title_query
from aqsd.torznab import fetch_torznab_candidates
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
    resolution: str | None = None
    groups: list[str] = field(default_factory=list)
    subtitle_type: str | None = None
    raw_only: bool = False
    exclude_batch: bool = False
    release_mode: str = "any"
    min_seeders: int = 0
    limit: int | None = None


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
    seen_title_episodes: set[tuple[str, str]] = set()
    attempted_sources: list[str] = []
    title_resolution = resolve_search_title(config, request.query)
    _hydrate_request_queries(request, title_resolution)
    logger.info("Search queries expanded: {}", ", ".join(request.expanded_queries or [request.query]))
    result.diagnostics = SearchDiagnostics(
        original_query=request.query,
        expanded_queries=list(request.expanded_queries or [request.query]),
        expanded_query_details=list(request.expanded_query_details),
        resolution_status=title_resolution.resolution_status,
        needs_review=title_resolution.needs_review,
        active_filters=_build_active_filters(request),
        resolved_subject=title_resolution.resolved_subject,
        candidate_subjects=list(title_resolution.candidate_subjects),
        rejected_subjects=list(title_resolution.rejected_subjects),
    )

    for source in config.rss_sources:
        if not source.enabled:
            continue

        if "RSS" not in attempted_sources:
            attempted_sources.append("RSS")
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
            seen_title_episodes,
        )

    nyaa_settings = config.search_sources.nyaa
    if nyaa_settings.enabled:
        attempted_sources.append("Nyaa")
        for query in _queries_for_source(request, "nyaa"):
            try:
                logger.info("Searching Nyaa: {}", query)
                items = fetch_nyaa_candidates(nyaa_settings, query, limit=request.limit)
            except Exception as exc:
                logger.warning("Nyaa search failed: query={} error={}", query, exc)
                continue

            result.rss_entries_total += len(items)
            _collect_search_matches(
                items,
                request,
                config,
                result,
                seen_urls,
                seen_hashes,
                seen_title_episodes,
            )

    torznab_settings = config.search_sources.torznab
    if torznab_settings.enabled:
        attempted_torznab = False
        for endpoint in torznab_settings.endpoints:
            if not endpoint.enabled:
                continue
            if not attempted_torznab:
                attempted_sources.append("Torznab")
                attempted_torznab = True
            for query in _queries_for_source(request, "torznab"):
                try:
                    logger.info("Searching Torznab: endpoint={} query={}", endpoint.name, query)
                    items = fetch_torznab_candidates(endpoint, query, limit=request.limit)
                except Exception as exc:
                    logger.warning("Torznab search failed: endpoint={} query={} error={}", endpoint.name, query, exc)
                    continue

                result.rss_entries_total += len(items)
                _collect_search_matches(
                    items,
                    request,
                    config,
                    result,
                    seen_urls,
                    seen_hashes,
                    seen_title_episodes,
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
        result.diagnostics.suggestions = _build_search_suggestions(result.diagnostics, config)

    return result


def resolve_search_title(config: AppConfig, query: str) -> TitleResolution:
    bangumi_settings = config.metadata_sources.bangumi
    anilist_settings = config.metadata_sources.anilist
    if not bangumi_settings.enabled and not anilist_settings.enabled:
        return resolve_title_query(query, config.title_aliases)

    cache = Database(config.app.database) if bangumi_settings.enabled or anilist_settings.cache_enabled else None
    try:
        return resolve_title_query(
            query,
            config.title_aliases,
            bangumi_settings=bangumi_settings,
            anilist_settings=anilist_settings,
            cache=cache,
        )
    finally:
        if cache is not None:
            cache.close()


def _hydrate_request_queries(request: SearchRequest, resolution: TitleResolution) -> None:
    if not request.expanded_query_details:
        request.expanded_query_details.extend(resolution.expanded_query_details)
    elif not any(normalize_text(detail.text) == normalize_text(request.query) for detail in request.expanded_query_details):
        request.expanded_query_details.insert(0, ExpandedQueryDetail(text=request.query, source="original", confidence=1.0, alias_confidence=1.0, search_role="secondary", search_tier="secondary"))

    if not request.expanded_queries:
        request.expanded_queries.extend(
            detail.text for detail in request.expanded_query_details if detail.search_eligible
        )
    if not request.expanded_queries:
        request.expanded_queries.append(request.query)


def _collect_search_matches(
    items: list[Candidate],
    request: SearchRequest,
    config: AppConfig,
    result: DiscoveryResult,
    seen_urls: set[str],
    seen_hashes: set[str],
    seen_title_episodes: set[tuple[str, str]],
) -> None:
    for item in items:
        if not item.url or item.url in seen_urls:
            continue

        candidate = parse_candidate(item)
        hash_key = _hash_key(candidate)
        if hash_key and hash_key in seen_hashes:
            continue

        duplicate_key = _title_episode_key(candidate)
        if duplicate_key and duplicate_key in seen_title_episodes:
            continue

        seen_urls.add(candidate.url)
        if hash_key:
            seen_hashes.add(hash_key)
        if duplicate_key:
            seen_title_episodes.add(duplicate_key)
        if result.diagnostics and result.diagnostics.candidate_count_before_filter is not None:
            result.diagnostics.candidate_count_before_filter += 1
        elif result.diagnostics:
            result.diagnostics.candidate_count_before_filter = 1

        if candidate.episode is not None:
            result.parsed_success_total += 1

        if not _matches_search_request(candidate, request):
            continue

        _score_search_candidate(candidate, request, config)
        result.candidates.append(candidate)


def _title_episode_key(candidate: Candidate) -> tuple[str, str] | None:
    if not candidate.episode:
        return None
    return normalize_text(candidate.title), candidate.episode


def _hash_key(candidate: Candidate) -> str | None:
    if not candidate.info_hash:
        return None
    return candidate.info_hash.strip().casefold() or None


def _matches_search_request(candidate: Candidate, request: SearchRequest) -> bool:
    matched_detail = _match_query_detail(candidate, request)
    if request.query and matched_detail is None:
        return False
    if matched_detail is not None:
        _attach_match_evidence(candidate, matched_detail)

    if request.exclude_batch and candidate.is_batch:
        return False

    if request.release_mode == "episode" and candidate.is_batch:
        return False

    if request.release_mode == "batch" and not candidate.is_batch:
        return False

    if request.episodes and not _episode_matches_request(candidate, request):
        return False

    if request.resolution and (candidate.resolution or "").casefold() != request.resolution.casefold():
        return False

    if request.groups and not _value_in_normalized_set(candidate.group, request.groups):
        return False

    if request.subtitle_type and (candidate.subtitle_type or "").casefold() != request.subtitle_type.casefold():
        return False

    if request.raw_only and not candidate.is_raw:
        return False

    if candidate.seeders < request.min_seeders:
        return False

    return True


def _match_query_detail(candidate: Candidate, request: SearchRequest) -> ExpandedQueryDetail | None:
    searchable_value = candidate.parsed_title or candidate.title
    details = request.expanded_query_details or [
        ExpandedQueryDetail(text=value, source="original", confidence=1.0, alias_confidence=1.0, search_role="secondary", search_tier="secondary")
        for value in (request.expanded_queries or [request.query])
        if value
    ]
    matched = [detail for detail in details if detail.search_eligible and contains_search_keyword(searchable_value, detail.text)]
    if matched:
        matched.sort(key=lambda detail: (detail.confidence, _search_role_rank(detail.search_role), len(normalize_text(detail.text))), reverse=True)
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


def _queries_for_source(request: SearchRequest, source_kind: str) -> list[str]:
    details = request.expanded_query_details or [
        ExpandedQueryDetail(text=value, source="original", confidence=1.0, alias_confidence=1.0, search_role="secondary", search_tier="secondary")
        for value in request.expanded_queries or [request.query]
    ]
    eligible = [detail for detail in details if detail.search_eligible]
    if not eligible:
        return [request.query]

    if source_kind == "nyaa":
        language_order = {"romaji": 5, "en": 4, "ja": 3, "zh": 2, "unknown": 1}
    else:
        language_order = {"romaji": 5, "en": 4, "zh": 3, "ja": 2, "unknown": 1}

    ranked = sorted(
        eligible,
        key=lambda detail: (
            _search_role_rank(detail.search_role),
            language_order.get(detail.language, 0),
            detail.confidence,
            len(normalize_text(detail.text)),
        ),
        reverse=True,
    )
    queries: list[str] = []
    seen: set[str] = set()
    for detail in ranked:
        key = detail.text.strip().casefold()
        if key in seen:
            continue
        seen.add(key)
        queries.append(detail.text)
    return queries[:6]


def _search_role_rank(role: str) -> int:
    return {"primary": 3, "secondary": 2, "display_only": 1}.get(role, 0)


def _episode_matches_request(candidate: Candidate, request: SearchRequest) -> bool:
    normalized_episodes = _normalize_episode_values(request.episodes)
    if (candidate.episode or "") in normalized_episodes:
        return True

    if candidate.is_batch and request.release_mode == "batch":
        return True

    return False


def _score_search_candidate(candidate: Candidate, request: SearchRequest, config: AppConfig) -> None:
    prefer_groups = request.groups or ([candidate.group] if candidate.group else [])
    rule = AnimeRule(
        name=request.query,
        prefer_groups=prefer_groups,
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


def _build_search_suggestions(diagnostics: SearchDiagnostics, config: AppConfig) -> list[str]:
    suggestions: list[str] = ["可先尝试解析标题，确认标题扩展是否符合预期。"]
    expanded = diagnostics.expanded_queries or [diagnostics.original_query]
    if len(expanded) <= 1:
        suggestions.append("可尝试换一个别名、英文名或日文名重新搜索。")

    before_count = diagnostics.candidate_count_before_filter or 0
    after_count = diagnostics.candidate_count_after_filter or 0
    filtered_out = before_count > 0 and after_count == 0
    no_results = after_count == 0

    if no_results and len(expanded) > 1:
        suggestions.append("可检查标题扩展结果，挑一个更接近作品名的标题重试。")

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
    if "raw_only" in diagnostics.active_filters and no_results:
        suggestions.append("只看 RAW 可能过严，可先取消 RAW 限制。")

    if not config.search_sources.nyaa.enabled and not config.search_sources.torznab.enabled:
        suggestions.append("可检查 config.yaml 的 search_sources，按需启用 Nyaa 或 Torznab。")

    deduped: list[str] = []
    for suggestion in suggestions:
        if suggestion not in deduped:
            deduped.append(suggestion)
    return deduped[:6]
