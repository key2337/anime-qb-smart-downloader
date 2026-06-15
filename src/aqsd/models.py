from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class ScoreReason:
    code: str
    delta: float
    message: str


@dataclass(slots=True)
class ScoreBreakdown:
    total: float = 0.0
    reasons: list[ScoreReason] = field(default_factory=list)


@dataclass(slots=True)
class ExpandedQueryDetail:
    text: str
    source: str
    confidence: float = 1.0
    subject_id: int | str | None = None
    language: str = "unknown"
    subject_confidence: float | None = None
    alias_confidence: float | None = None
    reason: str | None = None
    search_eligible: bool = True
    search_role: str = "primary"
    search_tier: str = "primary"


@dataclass(slots=True)
class ResolvedSubject:
    source: str
    subject_id: int | str | None
    canonical: str
    confidence: float
    confidence_level: str | None = None
    reason: str | None = None


@dataclass(slots=True)
class TitleEvidence:
    type: str
    score: float
    reason: str


@dataclass(slots=True)
class SearchDiagnostics:
    original_query: str
    expanded_queries: list[str] = field(default_factory=list)
    expanded_query_details: list[ExpandedQueryDetail] = field(default_factory=list)
    resolution_status: str = "unresolved"
    needs_review: bool = False
    sources: list[str] = field(default_factory=list)
    active_filters: dict[str, Any] = field(default_factory=dict)
    candidate_count_before_filter: int | None = None
    candidate_count_after_filter: int | None = None
    stage_counts: dict[str, int] = field(default_factory=dict)
    filter_drop_reasons: dict[str, int] = field(default_factory=dict)
    suggestions: list[str] = field(default_factory=list)
    resolved_subject: ResolvedSubject | None = None
    candidate_subjects: list[dict[str, Any]] = field(default_factory=list)
    rejected_subjects: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class Candidate:
    title: str
    url: str
    source: str
    magnet: str | None = None
    info_hash: str | None = None
    published_at: datetime | None = None
    seeders: int = 0

    anime_name: str | None = None
    season: int | None = None
    episode: str | None = None
    group: str | None = None
    resolution: str | None = None
    subtitle_type: str | None = None
    source_type: str | None = None
    parsed_title: str | None = None
    is_raw: bool = False
    is_batch: bool = False
    is_hevc: bool = False
    has_dual_audio: bool = False
    is_v2: bool = False

    score: float = 0.0
    breakdown: ScoreBreakdown | None = None
    score_reasons: list[str] = field(default_factory=list)
    matched_query: str | None = None
    matched_query_source: str | None = None
    matched_query_subject_id: int | str | None = None
    matched_query_confidence: float | None = None
    title_evidence: TitleEvidence | None = None
    matched_rule_name: str | None = None
    save_path: str | None = None
    category: str | None = None
    task_tag: str | None = None


@dataclass(slots=True)
class AnimeRule:
    name: str
    aliases: list[str] = field(default_factory=list)
    profile: str = "fastest"
    include: list[str] = field(default_factory=list)
    reject: list[str] = field(default_factory=list)
    prefer_groups: list[str] = field(default_factory=list)
    allow_hevc: bool | None = None
    allow_dual_audio: bool | None = None
    save_path: str | None = None
    category: str | None = None


@dataclass(slots=True)
class CartItem:
    title: str
    magnet: str | None = None
    url: str = ""
    source: str = ""
    seeders: int = 0
    score: float = 0.0
    info_hash: str | None = None
    group: str | None = None
    resolution: str | None = None
    subtitle_type: str | None = None
    is_batch: bool = False
    is_raw: bool = False
    episode: str | None = None
    season: int | None = None


@dataclass(slots=True)
class CartEvent:
    timestamp: str
    type: str
    message: str


@dataclass(slots=True)
class Cart:
    cart_id: str = ""
    anime_name: str = ""
    episode: str = ""
    items: list[CartItem] = field(default_factory=list)
    tried_hashes: list[str] = field(default_factory=list)
    active_hash: str | None = None
    active_title: str | None = None
    fallback_count: int = 0
    max_fallbacks: int = 3
    status: str = "idle"
    events: list[CartEvent] = field(default_factory=list)
    created_at: str = ""
    probe_duration_seconds: int = 20


@dataclass(slots=True)
class DownloadTask:
    task_tag: str
    anime_name: str
    episode: str
    title: str
    url: str
    selection_mode: str = "auto"
    candidate_score: float = 0.0
    source: str | None = None
    category: str | None = None
    save_path: str | None = None
    status: str = "submitted"
    torrent_hash: str | None = None
    retry_count: int = 0
    fallback_count: int = 0
    last_error: str | None = None
    last_progress: float = 0.0
    last_speed_kbps: float = 0.0


@dataclass(slots=True)
class Subscription:
    id: int
    name: str
    enabled: bool = True
    source_name: str = ""
    match_name: str = ""
    episode_offset: int = 0
    last_check_at: str | None = None
    last_episode: str | None = None


@dataclass(slots=True)
class SubscriptionCheckResult:
    subscription_name: str
    rss_entries: int = 0
    matched: int = 0
    new_episodes: list[str] = field(default_factory=list)
    created_carts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
