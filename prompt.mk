下面这份可以直接复制给 Codex，让它按这个项目初始化。

---

```text
项目名称：anime-qb-smart-downloader

目标：
做一个动漫 RSS 智能下载器。它从 RSS 源抓取候选种子，根据用户配置的策略过滤、评分、排序，然后通过 qBittorrent Web API 添加下载任务。下载后持续监控速度和进度，如果疑似死种或速度过低，自动切换备用候选。

第一版 MVP：
1. 支持 RSS 源
2. 支持番剧规则配置
3. 支持 profile：fastest / preferred_group / raw_only / quality_first
4. 支持候选过滤、评分、去重
5. 支持 qBittorrent Web API 添加任务
6. 使用 SQLite 记录已处理集数和候选
7. 支持下载监控与 fallback
```

---

## 目录结构

```text
anime-qb-smart-downloader/
├─ README.md
├─ pyproject.toml
├─ config.example.yaml
├─ data/
│  └─ app.db
├─ src/
│  └─ aqsd/
│     ├─ __init__.py
│     ├─ main.py
│     ├─ config.py
│     ├─ models.py
│     ├─ rss.py
│     ├─ parser.py
│     ├─ matcher.py
│     ├─ scorer.py
│     ├─ database.py
│     ├─ qbittorrent.py
│     ├─ downloader.py
│     ├─ monitor.py
│     └─ utils.py
└─ tests/
   ├─ test_parser.py
   ├─ test_matcher.py
   └─ test_scorer.py
```

---

## 配置文件：`config.example.yaml`

```yaml
app:
  database: "./data/app.db"
  interval_seconds: 300
  log_level: "INFO"

qbittorrent:
  base_url: "http://127.0.0.1:8080"
  username: "admin"
  password: "adminadmin"
  default_category: "Anime"
  default_save_path: "/downloads/anime"

rss_sources:
  - name: "mikan"
    url: "https://example.com/rss.xml"
    enabled: true

fallback_policy:
  enabled: true
  check_after_minutes: 10
  min_download_speed_kbps: 100
  min_progress_delta: 0.001
  max_retry_candidates: 5
  delete_failed_torrent: true

profiles:
  fastest:
    prefer:
      resolution: ["1080p", "2160p", "720p"]
      subtitle: "any"
    allow_fallback: true

  preferred_group:
    prefer:
      resolution: ["1080p", "720p"]
      subtitle: "embedded"
    allow_other_group: false
    allow_fallback: true
    wait_minutes_before_fallback: 60

  raw_only:
    must_include:
      - "1080p"
    prefer:
      - "RAW"
      - "WEB-DL"
    reject:
      - "CHS"
      - "CHT"
      - "简中"
      - "繁中"
      - "内嵌"
      - "字幕组"
    allow_subtitled: false
    allow_fallback: true

  quality_first:
    prefer:
      resolution: ["2160p", "1080p"]
      source: ["WEB-DL", "BluRay"]
    allow_fallback: true
    wait_minutes_before_fallback: 120

anime:
  - name: "Example Anime"
    aliases:
      - "示例动画"
      - "Example"
    profile: "fastest"
    include:
      - "1080p"
    reject:
      - "合集"
      - "Batch"
    prefer_groups:
      - "LoliHouse"
      - "喵萌奶茶屋"
    save_path: "/downloads/anime/Example Anime"
    category: "Anime"
```

---

## 核心模块职责

```text
config.py
读取 YAML 配置，提供全局配置对象。

models.py
定义 Candidate、AnimeRule、DownloadTask 等数据结构。

rss.py
抓取 RSS，输出原始 RSS item。

parser.py
解析标题：番名、集数、分辨率、字幕组、字幕类型、是否合集、是否修正版。

matcher.py
根据 anime 配置匹配候选，做硬过滤。

scorer.py
根据 seeders、发布时间、字幕组偏好、profile 偏好打分。

database.py
SQLite 读写：已下载记录、候选记录、任务记录。

qbittorrent.py
封装 qB Web API：登录、添加 torrent、查询 torrent 状态、删除任务。

downloader.py
主调度：拉 RSS → 解析 → 匹配 → 评分 → 添加最高分候选。

monitor.py
监控下载速度和进度，疑似死种时切换备用候选。

main.py
CLI 入口，支持 run-once 和 daemon 两种模式。
```

---

## 开发顺序

```text
第 1 步：初始化项目
- 创建 pyproject.toml
- 安装依赖：feedparser、PyYAML、requests、pydantic、loguru

第 2 步：实现配置读取
- 从 config.yaml 读取 qB、RSS、anime、profiles 配置

第 3 步：实现 RSS 抓取
- feedparser 读取 RSS item
- 提取 title、link、published、seeders，如果没有 seeders 则默认为 0

第 4 步：实现标题解析
- 解析分辨率：720p / 1080p / 2160p
- 解析集数：01 / 02 / 第01集 / E01
- 解析字幕组：[LoliHouse] 这种方括号前缀
- 识别 RAW / CHS / CHT / 简中 / 繁中 / 内嵌 / 外挂

第 5 步：实现匹配和过滤
- aliases 命中番名
- include 必须包含
- reject 不能包含
- profile 的 raw_only / preferred_group 规则生效

第 6 步：实现评分
- seeders 权重
- 发布时间越新加分
- prefer_groups 加分
- 分辨率加分
- RAW / 内嵌字幕根据 profile 加分

第 7 步：接入 SQLite
- 记录每一集是否已下载
- 记录候选池
- 记录当前活跃下载任务

第 8 步：接入 qB
- 登录 qB
- 添加 magnet/torrent
- 设置 category 和 save_path

第 9 步：实现 fallback
- 定时查询 qB 状态
- 如果速度过低、进度不动、连接 seed 为 0，则切换下一个候选

第 10 步：补测试
- parser 测试
- matcher 测试
- scorer 测试
```

---

## 第一版代码骨架

### `pyproject.toml`

```toml
[project]
name = "anime-qb-smart-downloader"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "feedparser>=6.0.11",
  "PyYAML>=6.0.1",
  "requests>=2.31.0",
  "pydantic>=2.6.0",
  "loguru>=0.7.2"
]

[project.scripts]
aqsd = "aqsd.main:main"
```

---

### `src/aqsd/models.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Candidate:
    title: str
    url: str
    source: str
    published_at: Optional[datetime] = None
    seeders: int = 0

    anime_name: Optional[str] = None
    episode: Optional[str] = None
    group: Optional[str] = None
    resolution: Optional[str] = None
    subtitle_type: Optional[str] = None
    is_raw: bool = False
    is_batch: bool = False
    is_v2: bool = False

    score: float = 0.0
    matched_rule_name: Optional[str] = None
    save_path: Optional[str] = None
    category: Optional[str] = None


@dataclass
class AnimeRule:
    name: str
    aliases: list[str] = field(default_factory=list)
    profile: str = "fastest"
    include: list[str] = field(default_factory=list)
    reject: list[str] = field(default_factory=list)
    prefer_groups: list[str] = field(default_factory=list)
    save_path: Optional[str] = None
    category: Optional[str] = None
```

---

### `src/aqsd/config.py`

```python
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


class AppConfig(BaseModel):
    raw: dict[str, Any]

    @property
    def qb(self) -> dict[str, Any]:
        return self.raw["qbittorrent"]

    @property
    def rss_sources(self) -> list[dict[str, Any]]:
        return self.raw.get("rss_sources", [])

    @property
    def anime_rules(self) -> list[dict[str, Any]]:
        return self.raw.get("anime", [])

    @property
    def profiles(self) -> dict[str, Any]:
        return self.raw.get("profiles", {})

    @property
    def fallback_policy(self) -> dict[str, Any]:
        return self.raw.get("fallback_policy", {})


def load_config(path: str | Path) -> AppConfig:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return AppConfig(raw=data)
```

---

### `src/aqsd/rss.py`

```python
from datetime import datetime
from email.utils import parsedate_to_datetime

import feedparser

from aqsd.models import Candidate


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except Exception:
        return None


def fetch_rss(source: dict) -> list[Candidate]:
    feed = feedparser.parse(source["url"])
    items: list[Candidate] = []

    for entry in feed.entries:
        title = entry.get("title", "")
        url = entry.get("link", "")
        published = entry.get("published") or entry.get("updated")

        items.append(
            Candidate(
                title=title,
                url=url,
                source=source["name"],
                published_at=parse_datetime(published),
                seeders=int(entry.get("seeders", 0) or 0),
            )
        )

    return items
```

---

### `src/aqsd/parser.py`

```python
import re

from aqsd.models import Candidate


RESOLUTION_RE = re.compile(r"(2160p|1080p|720p|480p)", re.I)
GROUP_RE = re.compile(r"^\[([^\]]+)\]")
EPISODE_RE_LIST = [
    re.compile(r"\b[Ee](\d{1,3})\b"),
    re.compile(r"\b(\d{1,3})\s*(?:v\d)?\b"),
    re.compile(r"第\s*(\d{1,3})\s*[集话話]"),
]


def parse_candidate(candidate: Candidate) -> Candidate:
    title = candidate.title

    group_match = GROUP_RE.search(title)
    if group_match:
        candidate.group = group_match.group(1)

    resolution_match = RESOLUTION_RE.search(title)
    if resolution_match:
        candidate.resolution = resolution_match.group(1).lower()

    for pattern in EPISODE_RE_LIST:
        match = pattern.search(title)
        if match:
            candidate.episode = match.group(1).zfill(2)
            break

    lower_title = title.lower()

    candidate.is_raw = "raw" in lower_title or "web-dl" in lower_title
    candidate.is_batch = any(x in lower_title for x in ["batch", "合集", "complete"])
    candidate.is_v2 = bool(re.search(r"\bv\d\b", lower_title))

    if any(x in title for x in ["外挂", "外挂字幕"]):
        candidate.subtitle_type = "external"
    elif any(x in title for x in ["CHS", "CHT", "简中", "繁中", "内嵌"]):
        candidate.subtitle_type = "embedded"
    elif candidate.is_raw:
        candidate.subtitle_type = "none"
    else:
        candidate.subtitle_type = "unknown"

    return candidate
```

---

### `src/aqsd/matcher.py`

```python
from aqsd.models import AnimeRule, Candidate


def text_contains_any(text: str, keywords: list[str]) -> bool:
    return any(k.lower() in text.lower() for k in keywords)


def build_rules(config_rules: list[dict]) -> list[AnimeRule]:
    return [AnimeRule(**rule) for rule in config_rules]


def match_candidate(
    candidate: Candidate,
    rules: list[AnimeRule],
    profiles: dict,
    default_category: str,
    default_save_path: str,
) -> Candidate | None:
    title = candidate.title

    for rule in rules:
        names = [rule.name] + rule.aliases
        if not text_contains_any(title, names):
            continue

        if rule.include and not text_contains_any(title, rule.include):
            continue

        if rule.reject and text_contains_any(title, rule.reject):
            continue

        profile = profiles.get(rule.profile, {})

        if rule.profile == "raw_only":
            reject = profile.get("reject", [])
            if reject and text_contains_any(title, reject):
                continue
            if candidate.subtitle_type not in ["none", "unknown"]:
                continue

        if rule.profile == "preferred_group":
            allow_other_group = profile.get("allow_other_group", True)
            if not allow_other_group and rule.prefer_groups:
                if candidate.group not in rule.prefer_groups:
                    continue

        candidate.matched_rule_name = rule.name
        candidate.anime_name = rule.name
        candidate.category = rule.category or default_category
        candidate.save_path = rule.save_path or default_save_path
        return candidate

    return None
```

---

### `src/aqsd/scorer.py`

```python
from datetime import datetime, timezone

from aqsd.models import AnimeRule, Candidate


def score_candidate(candidate: Candidate, rule: AnimeRule, profile: dict) -> float:
    score = 0.0

    score += candidate.seeders * 5

    if candidate.published_at:
        now = datetime.now(timezone.utc)
        age_hours = max((now - candidate.published_at).total_seconds() / 3600, 0)
        score += max(0, 48 - age_hours)

    if candidate.group and candidate.group in rule.prefer_groups:
        score += 80

    preferred_resolutions = profile.get("prefer", {}).get("resolution", [])
    if candidate.resolution in preferred_resolutions:
        index = preferred_resolutions.index(candidate.resolution)
        score += max(0, 30 - index * 10)

    if candidate.is_v2:
        score += 10

    if candidate.is_batch:
        score -= 100

    if profile.get("prefer") == "RAW" and candidate.is_raw:
        score += 30

    candidate.score = score
    return score
```

---

### `src/aqsd/qbittorrent.py`

```python
import requests


class QBittorrentClient:
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.session = requests.Session()

    def login(self) -> None:
        url = f"{self.base_url}/api/v2/auth/login"
        resp = self.session.post(
            url,
            data={"username": self.username, "password": self.password},
            timeout=10,
        )
        resp.raise_for_status()
        if resp.text != "Ok.":
            raise RuntimeError(f"qB login failed: {resp.text}")

    def add_torrent(self, url: str, category: str | None = None, save_path: str | None = None) -> None:
        data = {"urls": url}
        if category:
            data["category"] = category
        if save_path:
            data["savepath"] = save_path

        resp = self.session.post(
            f"{self.base_url}/api/v2/torrents/add",
            data=data,
            timeout=20,
        )
        resp.raise_for_status()

    def list_torrents(self) -> list[dict]:
        resp = self.session.get(f"{self.base_url}/api/v2/torrents/info", timeout=10)
        resp.raise_for_status()
        return resp.json()

    def delete_torrent(self, torrent_hash: str, delete_files: bool = False) -> None:
        resp = self.session.post(
            f"{self.base_url}/api/v2/torrents/delete",
            data={"hashes": torrent_hash, "deleteFiles": str(delete_files).lower()},
            timeout=10,
        )
        resp.raise_for_status()
```

---

### `src/aqsd/database.py`

```python
import sqlite3
from pathlib import Path

from aqsd.models import Candidate


SCHEMA = """
CREATE TABLE IF NOT EXISTS downloaded (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  anime_name TEXT NOT NULL,
  episode TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(anime_name, episode)
);

CREATE TABLE IF NOT EXISTS candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  anime_name TEXT,
  episode TEXT,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  score REAL DEFAULT 0,
  source TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class Database:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def already_downloaded(self, anime_name: str, episode: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM downloaded WHERE anime_name = ? AND episode = ?",
            (anime_name, episode),
        )
        return cur.fetchone() is not None

    def mark_downloaded(self, candidate: Candidate) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO downloaded(anime_name, episode, title, url)
            VALUES (?, ?, ?, ?)
            """,
            (candidate.anime_name, candidate.episode, candidate.title, candidate.url),
        )
        self.conn.commit()

    def save_candidate(self, candidate: Candidate) -> None:
        self.conn.execute(
            """
            INSERT INTO candidates(anime_name, episode, title, url, score, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.anime_name,
                candidate.episode,
                candidate.title,
                candidate.url,
                candidate.score,
                candidate.source,
            ),
        )
        self.conn.commit()
```

---

### `src/aqsd/downloader.py`

```python
from collections import defaultdict

from loguru import logger

from aqsd.database import Database
from aqsd.matcher import build_rules, match_candidate
from aqsd.parser import parse_candidate
from aqsd.qbittorrent import QBittorrentClient
from aqsd.rss import fetch_rss
from aqsd.scorer import score_candidate


def run_once(config) -> None:
    db = Database(config.raw["app"]["database"])

    qb_conf = config.qb
    qb = QBittorrentClient(
        base_url=qb_conf["base_url"],
        username=qb_conf["username"],
        password=qb_conf["password"],
    )
    qb.login()

    rules = build_rules(config.anime_rules)
    default_category = qb_conf.get("default_category", "Anime")
    default_save_path = qb_conf.get("default_save_path")

    candidate_pool = defaultdict(list)

    for source in config.rss_sources:
        if not source.get("enabled", True):
            continue

        logger.info(f"Fetching RSS: {source['name']}")
        for candidate in fetch_rss(source):
            candidate = parse_candidate(candidate)
            matched = match_candidate(
                candidate,
                rules,
                config.profiles,
                default_category,
                default_save_path,
            )
            if not matched:
                continue

            if not matched.anime_name or not matched.episode:
                continue

            if db.already_downloaded(matched.anime_name, matched.episode):
                continue

            rule = next(r for r in rules if r.name == matched.matched_rule_name)
            profile = config.profiles.get(rule.profile, {})
            score_candidate(matched, rule, profile)
            db.save_candidate(matched)

            key = (matched.anime_name, matched.episode)
            candidate_pool[key].append(matched)

    for key, candidates in candidate_pool.items():
        best = sorted(candidates, key=lambda x: x.score, reverse=True)[0]

        logger.info(f"Adding torrent: {best.title} score={best.score}")
        qb.add_torrent(
            best.url,
            category=best.category,
            save_path=best.save_path,
        )
        db.mark_downloaded(best)
```

---

### `src/aqsd/main.py`

```python
import argparse
import time

from loguru import logger

from aqsd.config import load_config
from aqsd.downloader import run_once


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--daemon", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)

    if not args.daemon:
        run_once(config)
        return

    interval = config.raw.get("app", {}).get("interval_seconds", 300)

    while True:
        try:
            run_once(config)
        except Exception as e:
            logger.exception(e)

        time.sleep(interval)


if __name__ == "__main__":
    main()
```

---

## 给 Codex 的实现要求

```text
请按上述目录结构创建项目。

要求：
1. 先保证 MVP 能运行。
2. 不要一次性做复杂 UI。
3. 所有配置都从 config.yaml 读取。
4. 先实现 RSS → 解析 → 匹配 → 评分 → 添加到 qB。
5. fallback 监控可以第二阶段实现，但数据库结构要预留。
6. parser、matcher、scorer 必须写单元测试。
7. 代码要可维护，不要把逻辑塞进 main.py。
```

---

## 下一阶段再加的功能

```text
第二阶段：
- fallback 候选切换
- 下载速度历史记录
- 字幕组历史表现评分
- Web UI
- Telegram / Bark / Gotify 通知
- Torznab 支持
- Nyaa fallback
- 修正版 v2/v3 自动替换
- Jellyfin/Plex 下载后整理
```

这版可以作为 **Codex 第一轮项目初始化 prompt**。
