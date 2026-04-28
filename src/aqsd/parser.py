from __future__ import annotations

import re

from aqsd.models import Candidate


RESOLUTION_RE = re.compile(r"\b(2160p|1080p|720p|480p)\b", re.IGNORECASE)
GROUP_RE = re.compile(r"^\[([^\]]+)\]")
CODEC_SUFFIX_GROUP_RE = re.compile(r"\b(?:x264|x265|h[\s.]?264|h[\s.]?265)[- ](?P<group>[A-Za-z][A-Za-z0-9-]{2,})\b", re.IGNORECASE)
EXPLICIT_EPISODE_PATTERNS = [
    re.compile(r"\b[Ss]\d{1,2}[Ee](?P<episode>\d{1,3})(?:[Vv](?P<revision>\d))?\b"),
    re.compile(r"\b[Ee][Pp]?(?P<episode>\d{1,3})(?:[Vv](?P<revision>\d))?\b"),
    re.compile(r"第\s*(?P<episode>\d{1,3})\s*[集话話]"),
]
SEASON_PATTERNS = [
    re.compile(r"\b[Ss](?P<season>\d{1,2})[Ee]\d{1,3}\b"),
    re.compile(r"\b[Ss](?P<season>\d{1,2})\b"),
    re.compile(r"\bSeason\s*(?P<season>\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\b(?P<season>\d{1,2})(?:st|nd|rd|th)\s+Season\b", re.IGNORECASE),
]
FALLBACK_EPISODE_RE = re.compile(r"(?:^|[\s\-_])(?P<episode>\d{1,3})(?:[Vv](?P<revision>\d))?(?=$|[\s\-_])")
SOURCE_PATTERNS = {
    "WEB-DL": re.compile(r"\bWEB[- ]?DL\b", re.IGNORECASE),
    "BLURAY": re.compile(r"\bBluRay\b", re.IGNORECASE),
    "WEBRip": re.compile(r"\bWEBRip\b", re.IGNORECASE),
}
HEVC_RE = re.compile(r"\b(?:hevc|x265|h[\s.]?265)\b", re.IGNORECASE)
DUAL_AUDIO_RE = re.compile(r"\bdual(?:[ -]?audio)?\b", re.IGNORECASE)
EXTERNAL_SUB_MARKERS = ("外挂", "外挂字幕", "external")
EMBEDDED_SUB_MARKERS = ("chs", "cht", "简中", "繁中", "内嵌", "中字", "简繁")
RAW_MARKERS = ("raw",)


def _clean_title_for_episode_search(title: str) -> str:
    cleaned = GROUP_RE.sub(" ", title, count=1)
    cleaned = RESOLUTION_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\[[^\]]+\]", " ", cleaned)
    cleaned = re.sub(r"\([^)]+\)", " ", cleaned)
    cleaned = re.sub(r"\b(?:x264|x265|h[\s.]?264|h[\s.]?265)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:aac|eac-?3|flac)\s*\d+(?:\.\d+)?\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d+bit\b", " ", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def _extract_episode(title: str) -> tuple[str | None, bool]:
    for pattern in EXPLICIT_EPISODE_PATTERNS:
        match = pattern.search(title)
        if match:
            episode = match.group("episode").zfill(2)
            return episode, bool(match.groupdict().get("revision"))

    cleaned = _clean_title_for_episode_search(title)
    match = FALLBACK_EPISODE_RE.search(cleaned)
    if not match:
        return None, False

    episode = match.group("episode").zfill(2)
    return episode, bool(match.groupdict().get("revision"))


def _extract_season(title: str) -> int | None:
    for pattern in SEASON_PATTERNS:
        match = pattern.search(title)
        if match:
            return int(match.group("season"))
    return None


def _extract_source_type(title: str) -> str | None:
    for source_name, pattern in SOURCE_PATTERNS.items():
        if pattern.search(title):
            return source_name
    return None


def _extract_release_group(title: str) -> str | None:
    group_match = GROUP_RE.search(title)
    if group_match:
        return group_match.group(1)

    suffix_match = CODEC_SUFFIX_GROUP_RE.search(title)
    if suffix_match:
        return suffix_match.group("group")

    return None


def _extract_subtitle_type(title: str, candidate: Candidate) -> str:
    lowered = title.casefold()

    if any(marker in lowered for marker in EXTERNAL_SUB_MARKERS):
        return "external"
    if any(marker in lowered for marker in EMBEDDED_SUB_MARKERS):
        return "embedded"
    if candidate.is_raw:
        return "none"
    return "unknown"


def _infer_parsed_title(title: str) -> str | None:
    parsed = GROUP_RE.sub(" ", title, count=1)
    parsed = re.sub(r"\[[^\]]+\]", " ", parsed)
    parsed = re.sub(r"\([^)]+\)", " ", parsed)
    parsed = RESOLUTION_RE.sub(" ", parsed)
    for pattern in EXPLICIT_EPISODE_PATTERNS:
        parsed = pattern.sub(" ", parsed)
    parsed = FALLBACK_EPISODE_RE.sub(" ", parsed)
    parsed = re.sub(r"\b(?:WEB[- ]?DL|BluRay|WEBRip|RAW|V\d)\b", " ", parsed, flags=re.IGNORECASE)
    parsed = re.sub(r"\s+", " ", parsed).strip(" -_")
    return parsed or None


def parse_candidate(candidate: Candidate) -> Candidate:
    title = candidate.title
    lower_title = title.casefold()

    candidate.group = _extract_release_group(title)

    resolution_match = RESOLUTION_RE.search(title)
    if resolution_match:
        candidate.resolution = resolution_match.group(1).lower()

    candidate.season = _extract_season(title)
    candidate.is_raw = any(marker in lower_title for marker in RAW_MARKERS)
    candidate.source_type = _extract_source_type(title)
    if candidate.source_type == "WEB-DL":
        candidate.is_raw = True

    candidate.is_batch = any(marker in lower_title for marker in ("batch", "合集", "complete"))
    candidate.is_hevc = bool(HEVC_RE.search(title))
    candidate.has_dual_audio = bool(DUAL_AUDIO_RE.search(title))
    candidate.episode, revision_from_episode = _extract_episode(title)
    candidate.is_v2 = revision_from_episode or bool(re.search(r"\bv[23]\b", lower_title))
    candidate.subtitle_type = _extract_subtitle_type(title, candidate)
    candidate.parsed_title = _infer_parsed_title(title)

    return candidate
