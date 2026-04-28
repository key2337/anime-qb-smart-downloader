from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from aqsd.config import AppConfig
from aqsd.matcher import match_candidate
from aqsd.models import Candidate
from aqsd.parser import parse_candidate
from aqsd.rss import fetch_rss, inspect_rss
from aqsd.scorer import explain_score_candidate


@dataclass(slots=True)
class DryRunReport:
    rss_entries_total: int
    parsed_success_total: int
    matched_total_before_latest_only: int
    matched_total: int
    top_candidates: list[Candidate]


def _candidate_episode_key(candidate: Candidate) -> tuple[int, int]:
    season = candidate.season or 0
    episode = int(candidate.episode or "0")
    return season, episode


def _filter_latest_only(candidates: list[Candidate]) -> tuple[list[Candidate], tuple[int, int] | None]:
    candidates_with_episode = [candidate for candidate in candidates if candidate.episode]
    if not candidates_with_episode:
        return candidates, None

    latest_key = max(_candidate_episode_key(candidate) for candidate in candidates_with_episode)
    filtered = [candidate for candidate in candidates_with_episode if _candidate_episode_key(candidate) == latest_key]
    return filtered, latest_key


def run_dry_run(config: AppConfig, limit: int = 10, latest_only: bool = True) -> DryRunReport:
    rules = config.anime_rules
    rule_by_name = {rule.name: rule for rule in rules}

    rss_entries_total = 0
    parsed_success_total = 0
    matched_candidates: list[Candidate] = []
    seen_urls: set[str] = set()

    for source in config.rss_sources:
        if not source.enabled:
            continue

        source_info = inspect_rss(source)
        rss_entries_total += int(source_info["entries"])
        logger.info(
            "Dry-run source: name={} entries={} title={}",
            source_info["name"],
            source_info["entries"],
            source_info["feed_title"] or "-",
        )

        for item in fetch_rss(source):
            if item.url in seen_urls:
                continue

            seen_urls.add(item.url)
            candidate = parse_candidate(item)
            if candidate.episode is not None:
                parsed_success_total += 1

            matched = match_candidate(
                candidate,
                rules,
                config.profiles,
                config.qb.default_category,
                config.qb.default_save_path,
            )
            if not matched:
                continue

            rule = rule_by_name[matched.matched_rule_name or ""]
            profile = config.profiles.get(rule.profile, {})
            matched_candidates.append(matched)

    matched_total_before_latest_only = len(matched_candidates)
    latest_episode_key: tuple[int, int] | None = None
    if latest_only:
        matched_candidates, latest_episode_key = _filter_latest_only(matched_candidates)
        if latest_episode_key is not None:
            logger.info(
                "Latest-only enabled: keeping candidates for S{:02d}E{:02d}",
                latest_episode_key[0],
                latest_episode_key[1],
            )

    for matched in matched_candidates:
        rule = rule_by_name[matched.matched_rule_name or ""]
        profile = config.profiles.get(rule.profile, {})
        explain_score_candidate(matched, rule, profile, latest_episode_key=latest_episode_key)

    top_candidates = sorted(
        matched_candidates,
        key=lambda item: (item.score, item.seeders, item.title),
        reverse=True,
    )[:limit]

    logger.info(
        "Dry-run summary: rss_entries_total={} parsed_success_total={} matched_total_before_latest_only={} matched_total={}",
        rss_entries_total,
        parsed_success_total,
        matched_total_before_latest_only,
        len(matched_candidates),
    )

    for index, candidate in enumerate(top_candidates, start=1):
        logger.info(
            "Top {}: score={:.1f} episode={} resolution={} group={} title={}",
            index,
            candidate.score,
            candidate.episode or "-",
            candidate.resolution or "-",
            candidate.group or "-",
            candidate.title,
        )
        for reason in candidate.score_reasons:
            logger.info("  reason: {}", reason)

    return DryRunReport(
        rss_entries_total=rss_entries_total,
        parsed_success_total=parsed_success_total,
        matched_total_before_latest_only=matched_total_before_latest_only,
        matched_total=len(matched_candidates),
        top_candidates=top_candidates,
    )
