from __future__ import annotations

import re
import uuid
from collections.abc import Iterable


_NORMALIZE_RE = re.compile(r"[\s\[\]\(\)\{\}_\-.|/\\]+")


def normalize_text(value: str) -> str:
    return _NORMALIZE_RE.sub("", value).casefold()


def contains_any_keyword(text: str, keywords: Iterable[str]) -> bool:
    normalized_text = normalize_text(text)
    return any(keyword and normalize_text(keyword) in normalized_text for keyword in keywords)


def contains_all_keywords(text: str, keywords: Iterable[str]) -> bool:
    normalized_text = normalize_text(text)
    return all(keyword and normalize_text(keyword) in normalized_text for keyword in keywords)


def build_task_tag(anime_name: str, episode: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", normalize_text(anime_name)).strip("-")
    suffix = uuid.uuid4().hex[:8]
    return f"aqsd-{normalized or 'anime'}-{episode}-{suffix}"
