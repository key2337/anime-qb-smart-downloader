from __future__ import annotations

import re
import uuid
from collections.abc import Iterable


_NORMALIZE_RE = re.compile(r"[\s\[\]\(\)\{\}_\-.|/\\]+")
_ASCII_TOKEN_RE = re.compile(r"[a-z0-9]+")


def normalize_text(value: str) -> str:
    return _NORMALIZE_RE.sub("", value).casefold()


def tokenize_ascii_words(value: str) -> list[str]:
    return _ASCII_TOKEN_RE.findall(value.casefold())


def contains_any_keyword(text: str, keywords: Iterable[str]) -> bool:
    normalized_text = normalize_text(text)
    return any(keyword and normalize_text(keyword) in normalized_text for keyword in keywords)


def contains_all_keywords(text: str, keywords: Iterable[str]) -> bool:
    normalized_text = normalize_text(text)
    return all(keyword and normalize_text(keyword) in normalized_text for keyword in keywords)


def contains_search_keyword(text: str, keyword: str) -> bool:
    stripped_keyword = keyword.strip()
    if not stripped_keyword:
        return False

    keyword_tokens = tokenize_ascii_words(stripped_keyword)
    if keyword_tokens:
        text_tokens = tokenize_ascii_words(text)
        if len(keyword_tokens) == 1:
            token = keyword_tokens[0]
            if len(token) <= 4:
                return token in text_tokens
            return token in text_tokens or normalize_text(stripped_keyword) in normalize_text(text)
        return _contains_token_sequence(text_tokens, keyword_tokens)

    return normalize_text(stripped_keyword) in normalize_text(text)


def contains_any_search_keyword(text: str, keywords: Iterable[str]) -> bool:
    return any(contains_search_keyword(text, keyword) for keyword in keywords)


def _contains_token_sequence(text_tokens: list[str], keyword_tokens: list[str]) -> bool:
    if not keyword_tokens:
        return False
    window = len(keyword_tokens)
    return any(text_tokens[index : index + window] == keyword_tokens for index in range(len(text_tokens) - window + 1))


def build_task_tag(anime_name: str, episode: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", normalize_text(anime_name)).strip("-")
    suffix = uuid.uuid4().hex[:8]
    return f"aqsd-{normalized or 'anime'}-{episode}-{suffix}"


def fix_magnet_name(url: str, title: str | None) -> str:
    """Inject display name into magnet URI when dn parameter is missing or empty."""
    if not url.casefold().startswith("magnet:"):
        return url
    if not title:
        return url
    from urllib.parse import quote

    if "dn=" in url:
        url = re.sub(r"dn=[^&]*", f"dn={quote(title)}", url)
    else:
        url = re.sub(r"magnet:\?(?=xt)", f"magnet:?dn={quote(title)}&", url)
    return url
