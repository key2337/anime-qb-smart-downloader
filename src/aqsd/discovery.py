from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from loguru import logger

from aqsd.config import AppConfig
from aqsd.database import Database
from aqsd.matcher import match_candidate
from aqsd.models import AnimeRule, Candidate
from aqsd.parser import parse_candidate
from aqsd.rss import fetch_rss
from aqsd.scorer import score_candidate
from aqsd.utils import contains_all_keywords, contains_any_keyword, normalize_text


@dataclass(slots=True)
class DiscoveryResult:
    rss_entries_total: int = 0
    parsed_success_total: int = 0
    candidates: list[Candidate] = field(default_factory=list)

    @property
    def matched_total(self) -> int:
        return len(self.candidates)


@dataclass(slots=True)
class SearchRequest:
    query: str
    episodes: list[str] = field(default_factory=list)
    resolution: str | None = None
    groups: list[str] = field(default_factory=list)
    subtitle_type: str | None = None
    raw_only: bool = False
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

            if not _matches_search_request(candidate, request):
                continue

            _score_search_candidate(candidate, request, config)
            result.candidates.append(candidate)

    result.candidates = sorted(
        result.candidates,
        key=lambda item: (item.score, item.seeders, item.title),
        reverse=True,
    )
    if request.limit is not None:
        result.candidates = result.candidates[: request.limit]

    return result


def _matches_search_request(candidate: Candidate, request: SearchRequest) -> bool:
    if request.query:
        searchable_values = [candidate.title]
        if candidate.parsed_title:
            searchable_values.append(candidate.parsed_title)
        if not any(contains_any_keyword(value, [request.query]) for value in searchable_values):
            return False

    if request.episodes and (candidate.episode or "") not in _normalize_episode_values(request.episodes):
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
    score_candidate(candidate, rule, profile={})


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
