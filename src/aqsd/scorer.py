from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aqsd.models import AnimeRule, Candidate, ExpandedQueryDetail, ScoreBreakdown, ScoreReason
from aqsd.utils import contains_search_keyword, normalize_text


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
    if not rule.prefer_groups:
        return 0.0

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


def _add_reason(breakdown: ScoreBreakdown, code: str, delta: float, message: str) -> None:
    breakdown.total += delta
    breakdown.reasons.append(ScoreReason(code=code, delta=delta, message=message))


def _format_score_value(value: float) -> str:
    rounded = round(value)
    if abs(value - rounded) < 1e-9:
        return str(int(rounded))
    return f"{value:.1f}".rstrip("0").rstrip(".")


def render_score_reason(reason: ScoreReason) -> str:
    return f"{reason.delta:+.1f}".rstrip("0").rstrip(".") + f" {reason.message}"


def _apply_search_request_reasons(
    breakdown: ScoreBreakdown,
    candidate: Candidate,
    search_context: dict[str, Any],
) -> None:
    query = str(search_context.get("query") or "").strip()
    matched_detail = _resolve_matched_query_detail(candidate, search_context, query)
    if matched_detail:
        delta, code, message = _title_match_reason(matched_detail, query)
        _add_reason(breakdown, code, delta, message)

    if candidate.episode and candidate.episode in set(search_context.get("episodes", [])):
        _add_reason(breakdown, "episode_match", 20.0, f"episode matched: {candidate.episode}")

    requested_resolution = str(search_context.get("resolution") or "").strip()
    if requested_resolution and candidate.resolution and candidate.resolution.casefold() == requested_resolution.casefold():
        _add_reason(breakdown, "resolution_match", 15.0, f"resolution matched: {candidate.resolution}")

    requested_subtitle = str(search_context.get("subtitle_type") or "").strip()
    if requested_subtitle and candidate.subtitle_type and candidate.subtitle_type.casefold() == requested_subtitle.casefold():
        _add_reason(breakdown, "subtitle_match", 8.0, f"subtitle matched: {candidate.subtitle_type}")

    requested_groups = [str(value) for value in search_context.get("groups", []) if str(value).strip()]
    if requested_groups and candidate.group and any(normalize_text(value) == normalize_text(candidate.group) for value in requested_groups):
        _add_reason(breakdown, "group_match", 10.0, f"requested group matched: {candidate.group}")

    if search_context.get("raw_only") and candidate.is_raw:
        _add_reason(breakdown, "raw_match", 12.0, "RAW-only filter matched")

    min_seeders = int(search_context.get("min_seeders") or 0)
    if min_seeders > 0 and candidate.seeders >= min_seeders:
        _add_reason(breakdown, "min_seeders_match", 5.0, f"meets minimum seeders: {candidate.seeders}")


def _resolve_matched_query_detail(
    candidate: Candidate,
    search_context: dict[str, Any],
    query: str,
) -> ExpandedQueryDetail | None:
    if candidate.matched_query:
        return ExpandedQueryDetail(
            text=candidate.matched_query,
            source=candidate.matched_query_source or "original",
            confidence=float(candidate.matched_query_confidence or 1.0),
            subject_id=candidate.matched_query_subject_id,
            language=_language_from_evidence(candidate),
            alias_confidence=float(candidate.matched_query_confidence or 1.0),
            reason=candidate.title_evidence.reason if candidate.title_evidence else None,
            search_eligible=True,
            search_role=_role_from_source(candidate.matched_query_source or "original", float(candidate.matched_query_confidence or 0.60)),
            search_tier=_role_from_source(candidate.matched_query_source or "original", float(candidate.matched_query_confidence or 0.60)),
        )

    details = [
        value
        for value in search_context.get("expanded_query_details", [])
        if isinstance(value, ExpandedQueryDetail) and value.search_eligible
    ]
    searchable_title = candidate.parsed_title or candidate.title
    for detail in sorted(details, key=lambda item: (item.confidence, _role_rank(item.search_role)), reverse=True):
        if contains_search_keyword(searchable_title, detail.text):
            return detail

    expanded_queries = [str(value) for value in search_context.get("expanded_queries", []) if str(value).strip()]
    matched_query = next((value for value in expanded_queries if contains_search_keyword(searchable_title, value)), None)
    if matched_query:
        confidence = 0.60 if normalize_text(matched_query) == normalize_text(query) else 0.50
        return ExpandedQueryDetail(
            text=matched_query,
            source="original" if normalize_text(matched_query) == normalize_text(query) else "expanded",
            confidence=confidence,
            language="unknown",
            alias_confidence=confidence,
            search_eligible=True,
            search_role="secondary",
            search_tier="secondary",
        )
    if query and contains_search_keyword(searchable_title, query):
        return ExpandedQueryDetail(
            text=query,
            source="original",
            confidence=1.0,
            language="unknown",
            alias_confidence=1.0,
            search_eligible=True,
            search_role="secondary",
            search_tier="secondary",
        )
    return None


def _title_match_reason(detail: ExpandedQueryDetail, query: str) -> tuple[float, str, str]:
    language_label = detail.language or "unknown"
    if detail.search_role == "primary" and detail.confidence >= 0.85:
        return (
            25.0,
            "title_resolved_subject_match",
            f"title matched resolved subject via {language_label} title: {detail.text}",
        )
    if detail.confidence >= 0.60:
        return (
            12.0,
            "title_secondary_alias_match",
            f"title matched secondary alias: {detail.text}",
        )
    return (
        5.0,
        "title_weak_alias_match",
        f"weak title match via low-confidence alias: {detail.text}",
    )


def _language_from_evidence(candidate: Candidate) -> str:
    evidence_type = candidate.title_evidence.type if candidate.title_evidence else ""
    if "_" in evidence_type:
        return evidence_type.split("_", 1)[0]
    return "unknown"


def _role_from_source(source: str, confidence: float) -> str:
    if source == "local" and confidence >= 0.85:
        return "primary"
    return "secondary"


def _role_rank(role: str) -> int:
    return {"primary": 2, "secondary": 1}.get(role, 0)


def explain_score_candidate(
    candidate: Candidate,
    rule: AnimeRule,
    profile: dict[str, Any],
    now: datetime | None = None,
    latest_episode_key: tuple[int, int] | None = None,
    search_context: dict[str, Any] | None = None,
) -> tuple[float, ScoreBreakdown]:
    breakdown = ScoreBreakdown()
    current_time = now or _utc_now()

    if search_context:
        _apply_search_request_reasons(breakdown, candidate, search_context)

    seeder_score = _score_seeders(candidate)
    _add_reason(breakdown, "seeders", seeder_score, f"seeders: {candidate.seeders}")

    freshness_score, age_hours = _score_freshness(candidate, current_time)
    if age_hours is not None:
        _add_reason(breakdown, "freshness", freshness_score, f"release freshness: age {age_hours:.1f}h")

    group_score = _score_group_preference(candidate, rule)
    if group_score > 0:
        _add_reason(breakdown, "preferred_group", group_score, f"preferred group: {candidate.group}")
    elif group_score < 0:
        _add_reason(breakdown, "group_penalty", group_score, f"group penalty: {candidate.group or 'unknown'}")

    if latest_episode_key is not None and _candidate_episode_key(candidate) == latest_episode_key:
        _add_reason(
            breakdown,
            "latest_episode_bonus",
            LATEST_EPISODE_BONUS,
            f"latest episode bonus: S{latest_episode_key[0]:02d}E{latest_episode_key[1]:02d}",
        )

    prefer = profile.get("prefer", {})
    if isinstance(prefer, dict):
        resolution_score = _score_ranked_preference(candidate.resolution, prefer.get("resolution", []), base=36)
        if resolution_score:
            _add_reason(breakdown, "preferred_resolution", resolution_score, f"preferred resolution: {candidate.resolution}")

        source_score = _score_ranked_preference(candidate.source_type, prefer.get("source", []), base=24)
        if source_score:
            _add_reason(breakdown, "preferred_source", source_score, f"preferred source: {candidate.source_type}")

        subtitle_score = _score_subtitle(candidate, prefer)
        if subtitle_score:
            _add_reason(breakdown, "preferred_subtitle", subtitle_score, f"preferred subtitle: {candidate.subtitle_type}")

    raw_score = _score_raw_preference(candidate, profile)
    if raw_score:
        raw_label = candidate.source_type or ("RAW" if candidate.is_raw else "source")
        _add_reason(breakdown, "raw_preference", raw_score, f"preferred RAW/source: {raw_label}")

    if candidate.is_v2:
        _add_reason(breakdown, "revision_bonus", 10.0, "revision bonus: v2/v3")

    if candidate.is_batch:
        _add_reason(breakdown, "batch_penalty", -120.0, "batch penalty")
    else:
        _add_reason(breakdown, "single_release_bonus", 6.0, "single release")

    candidate.score = breakdown.total
    candidate.breakdown = breakdown
    candidate.score_reasons = [render_score_reason(reason) for reason in breakdown.reasons]
    return breakdown.total, breakdown


def score_candidate(
    candidate: Candidate,
    rule: AnimeRule,
    profile: dict[str, Any],
    now: datetime | None = None,
    latest_episode_key: tuple[int, int] | None = None,
    search_context: dict[str, Any] | None = None,
) -> float:
    score, _ = explain_score_candidate(
        candidate,
        rule,
        profile,
        now=now,
        latest_episode_key=latest_episode_key,
        search_context=search_context,
    )
    return score
