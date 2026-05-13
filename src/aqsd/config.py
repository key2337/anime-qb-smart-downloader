from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from aqsd.models import AnimeRule


class AppSettings(BaseModel):
    database: str = "./data/app.db"
    interval_seconds: int = 300
    log_level: str = "INFO"


class QBittorrentSettings(BaseModel):
    base_url: str
    username: str
    password: str
    default_category: str = "Anime"
    default_save_path: str | None = None


class RSSSourceSettings(BaseModel):
    name: str
    url: str
    enabled: bool = True


class NyaaSearchSourceSettings(BaseModel):
    enabled: bool = False
    base_url: str = "https://nyaa.si"
    default_category: str = "1_2"
    timeout_seconds: int = 15


class TorznabEndpointSettings(BaseModel):
    name: str
    url: str
    api_key: str
    categories: list[str] = Field(default_factory=list)
    timeout_seconds: int = 15
    enabled: bool = True


class TorznabSearchSourceSettings(BaseModel):
    enabled: bool = False
    endpoints: list[TorznabEndpointSettings] = Field(default_factory=list)


class SearchSourcesSettings(BaseModel):
    nyaa: NyaaSearchSourceSettings = Field(default_factory=NyaaSearchSourceSettings)
    torznab: TorznabSearchSourceSettings = Field(default_factory=TorznabSearchSourceSettings)


class AniListMetadataSourceSettings(BaseModel):
    enabled: bool = False
    endpoint: str = "https://graphql.anilist.co"
    timeout_seconds: int = 15
    cache_enabled: bool = True
    cache_ttl_days: int = 30


class BangumiMetadataSourceSettings(BaseModel):
    enabled: bool = False
    timeout_seconds: int = 8
    max_results: int = 5


class MetadataSourcesSettings(BaseModel):
    bangumi: BangumiMetadataSourceSettings = Field(default_factory=BangumiMetadataSourceSettings)
    anilist: AniListMetadataSourceSettings = Field(default_factory=AniListMetadataSourceSettings)


class FallbackPolicy(BaseModel):
    enabled: bool = True
    check_after_minutes: int = 10
    min_download_speed_kbps: int = 100
    min_progress_delta: float = 0.001
    max_retry_candidates: int = 5
    delete_failed_torrent: bool = True


class ProbePolicy(BaseModel):
    enabled: bool = False
    max_candidates: int = 3
    duration_seconds: int = 30
    min_speed_kbps: int = 50
    delete_losers: bool = True


class TitleAliasSettings(BaseModel):
    canonical: str
    aliases: list[str] = Field(default_factory=list)


class AnimeRuleSettings(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    profile: str = "fastest"
    include: list[str] = Field(default_factory=list)
    reject: list[str] = Field(default_factory=list)
    prefer_groups: list[str] = Field(default_factory=list)
    allow_hevc: bool | None = None
    allow_dual_audio: bool | None = None
    save_path: str | None = None
    category: str | None = None

    def to_rule(self) -> AnimeRule:
        return AnimeRule(**self.model_dump())


class AppConfig(BaseModel):
    app: AppSettings = Field(default_factory=AppSettings)
    qbittorrent: QBittorrentSettings
    rss_sources: list[RSSSourceSettings] = Field(default_factory=list)
    search_sources: SearchSourcesSettings = Field(default_factory=SearchSourcesSettings)
    metadata_sources: MetadataSourcesSettings = Field(default_factory=MetadataSourcesSettings)
    fallback_policy: FallbackPolicy = Field(default_factory=FallbackPolicy)
    probe_policy: ProbePolicy = Field(default_factory=ProbePolicy)
    title_aliases: list[TitleAliasSettings] = Field(default_factory=list)
    profiles: dict[str, dict[str, Any]] = Field(default_factory=dict)
    anime: list[AnimeRuleSettings] = Field(default_factory=list)

    @property
    def qb(self) -> QBittorrentSettings:
        return self.qbittorrent

    @property
    def anime_rules(self) -> list[AnimeRule]:
        return [rule.to_rule() for rule in self.anime]


def load_config(path: str | Path) -> AppConfig:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return AppConfig.model_validate(data)
