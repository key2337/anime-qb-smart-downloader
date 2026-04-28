from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aqsd.models import AnimeRule, Candidate


GROUP_PREFERENCE_BASE = 240.0
GROUP_PREFERENCE_STEP = 60.0
NON_PREFERRED_GROUP_PENALTY = -70.0
UNKNOWN_GROUP_PENALTY = -90.0
MAX_SEEDER_SCORE = 100.0
MAX_FRESHNESS_SCORE = 140.0
FRESHNESS_WINDOW_HOURS = 24 * 45
LATEST_EPISODE_BONUS = 180.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _score_ranked_preference(value: str | None, preferred: list[str], base: int) -> float:
    if not value or value not in preferred:
        return 0.0
    index = preferred.index(value)
    return max(0.0, base - index * 12)


def _score_subtitle(candidate: Candidate, prefer: dict[str, Any]) -> float:
    subtitle_preference = prefer.get("subtitle")
    if subtitle_preference == "embedded" and candidate.subtitle_type == "embedded":
        return 15.0
    if subtitle_preference == "none" and candidate.subtitle_type == "none":
        return 15.0
    return 0.0


def _score_raw_preference(candidate: Candidate, profile: dict[str, Any]) -> float:
    prefer = profile.get("prefer", [])
    if isinstance(prefer, list):
        normalized = {item.casefold() for item in prefer}
        if candidate.is_raw and ("raw" in normalized or "web-dl" in normalized):
            return 20.0
        if candidate.source_type and candidate.source_type.casefold() in normalized:
            return 20.0
    return 0.0


def _score_seeders(candidate: Candidate) -> float:
    return min(MAX_SEEDER_SCORE, candidate.seeders * 0.25)


def _score_freshness(candidate: Candidate, current_time: datetime) -> tuple[float, float | None]:
    if not candidate.published_at:
        return 0.0, None

    age_hours = max((_ensure_aware(current_time) - _ensure_aware(candidate.published_at)).total_seconds() / 3600, 0)
    freshness_score = max(0.0, FRESHNESS_WINDOW_HOURS - age_hours) / FRESHNESS_WINDOW_HOURS * MAX_FRESHNESS_SCORE
    return freshness_score, age_hours


def _score_group_preference(candidate: Candidate, rule: AnimeRule) -> float:
    if not candidate.group:
        return UNKNOWN_GROUP_PENALTY

    if candidate.group in rule.prefer_groups:
        index = rule.prefer_groups.index(candidate.group)
        return max(0.0, GROUP_PREFERENCE_BASE - index * GROUP_PREFERENCE_STEP)

    return NON_PREFERRED_GROUP_PENALTY


def _candidate_episode_key(candidate: Candidate) -> tuple[int, int]:
    season = candidate.season or 0
    episode = int(candidate.episode or "0")
    return season, episode


def explain_score_candidate(
    candidate: Candidate,
    rule: AnimeRule,
    profile: dict[str, Any],
    now: datetime | None = None,
    latest_episode_key: tuple[int, int] | None = None,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    current_time = now or _utc_now()

    seeder_score = _score_seeders(candidate)
    score += seeder_score
    reasons.append(f"seeders: +{seeder_score:.1f} (capped from {candidate.seeders})")

    freshness_score, age_hours = _score_freshness(candidate, current_time)
    if age_hours is not None:
        score += freshness_score
        reasons.append(f"freshness: +{freshness_score:.1f} (age {age_hours:.1f}h)")

    group_score = _score_group_preference(candidate, rule)
    score += group_score
    if group_score >= 0:
        reasons.append(f"release group preference: +{group_score:.1f} ({candidate.group})")
    else:
        reasons.append(f"release group penalty: {group_score:.1f} ({candidate.group or 'unknown'})")

    if latest_episode_key is not None and _candidate_episode_key(candidate) == latest_episode_key:
        score += LATEST_EPISODE_BONUS
        reasons.append(
            f"latest episode bonus: +{LATEST_EPISODE_BONUS:.1f} (S{latest_episode_key[0]:02d}E{latest_episode_key[1]:02d})"
        )

    prefer = profile.get("prefer", {})
    if isinstance(prefer, dict):
        resolution_score = _score_ranked_preference(candidate.resolution, prefer.get("resolution", []), base=36)
        if resolution_score:
            score += resolution_score
            reasons.append(f"resolution preference: +{resolution_score:.1f} ({candidate.resolution})")

        source_score = _score_ranked_preference(candidate.source_type, prefer.get("source", []), base=24)
        if source_score:
            score += source_score
            reasons.append(f"source preference: +{source_score:.1f} ({candidate.source_type})")

        subtitle_score = _score_subtitle(candidate, prefer)
        if subtitle_score:
            score += subtitle_score
            reasons.append(f"subtitle preference: +{subtitle_score:.1f} ({candidate.subtitle_type})")

    raw_score = _score_raw_preference(candidate, profile)
    if raw_score:
        score += raw_score
        reasons.append(f"raw/source bonus: +{raw_score:.1f}")

    if candidate.is_v2:
        score += 10.0
        reasons.append("revision bonus: +10.0 (v2/v3)")

    if candidate.is_batch:
        score -= 120.0
        reasons.append("batch penalty: -120.0")

    candidate.score = score
    candidate.score_reasons = reasons
    return score, reasons


def score_candidate(
    candidate: Candidate,
    rule: AnimeRule,
    profile: dict[str, Any],
    now: datetime | None = None,
    latest_episode_key: tuple[int, int] | None = None,
) -> float:
    score, _ = explain_score_candidate(candidate, rule, profile, now=now, latest_episode_key=latest_episode_key)
    return score
