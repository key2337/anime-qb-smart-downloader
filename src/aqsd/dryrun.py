from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from aqsd.config import AppConfig
from aqsd.discovery import discover_rule_candidates
from aqsd.models import Candidate
from aqsd.scorer import explain_score_candidate
from aqsd.utils import candidate_episode_key


@dataclass(slots=True)
class DryRunReport:
    rss_entries_total: int
    parsed_success_total: int
    matched_total_before_latest_only: int
    matched_total: int
    top_candidates: list[Candidate]


def _filter_latest_only(candidates: list[Candidate]) -> tuple[list[Candidate], tuple[int, int] | None]:
    candidates_with_episode = [candidate for candidate in candidates if candidate.episode]
    if not candidates_with_episode:
        return candidates, None

    latest_key = max(candidate_episode_key(candidate) for candidate in candidates_with_episode)
    filtered = [candidate for candidate in candidates_with_episode if candidate_episode_key(candidate) == latest_key]
    return filtered, latest_key


def run_dry_run(config: AppConfig, limit: int = 10, latest_only: bool = True) -> DryRunReport:
    rules = config.anime_rules
    rule_by_name = {rule.name: rule for rule in rules}
    discovery = discover_rule_candidates(
        config,
        skip_downloaded=False,
        persist_candidates=False,
    )
    rss_entries_total = discovery.rss_entries_total
    parsed_success_total = discovery.parsed_success_total
    matched_candidates = discovery.candidates

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
