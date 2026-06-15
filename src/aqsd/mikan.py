"""Mikan Project helpers: .torrent info_hash extraction and enrichment."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any

import requests
from loguru import logger

from aqsd.bencode import extract_info_hash
from aqsd.models import Candidate

USER_AGENT = "aqsd/0.1.0"
REQUEST_TIMEOUT = 15
MAX_WORKERS = 3
CACHE_TTL_SECONDS = 3600

_cache: dict[str, tuple[str, float]] = {}
_cache_lock = Lock()


def enrich_candidates_with_info_hash(candidates: list[Candidate]) -> int:
    """Download .torrent files for candidates without info_hash, extract and set it.

    Uses a small thread pool for parallel downloads.  Results are cached by URL
    for one hour to avoid re-downloading the same .torrent across RSS checks.
    Returns the number of candidates successfully enriched.
    """
    needs_enrich = [c for c in candidates if not c.info_hash and c.url and c.url.startswith("http")]
    if not needs_enrich:
        return 0

    enriched = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_fetch_and_extract, c.url): c for c in needs_enrich}
        for future in futures:
            try:
                info_hash = future.result()
            except Exception:
                continue
            if info_hash:
                futures[future].info_hash = info_hash
                enriched += 1

    return enriched


def _fetch_and_extract(url: str) -> str | None:
    """Download a .torrent file and extract its info_hash.  Returns None on failure."""
    with _cache_lock:
        entry = _cache.get(url)
        if entry is not None:
            cached_hash, cached_at = entry
            if time.monotonic() - cached_at < CACHE_TTL_SECONDS:
                return cached_hash

    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Referer": _referer_for_url(url)},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        info_hash = extract_info_hash(response.content)
    except Exception:
        logger.debug("Failed to extract info_hash from {}", url)
        return None

    with _cache_lock:
        _cache[url] = (info_hash, time.monotonic())

    return info_hash


def _referer_for_url(url: str) -> str:
    """Derive a plausible Referer from the URL for Mikan's download protection."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/"
