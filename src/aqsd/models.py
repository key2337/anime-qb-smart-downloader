from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Candidate:
    title: str
    url: str
    source: str
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
    score_reasons: list[str] = field(default_factory=list)
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
