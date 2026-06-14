from __future__ import annotations

import re

from aqsd.models import Candidate


RESOLUTION_RE = re.compile(r"\b(3840x2160|1920x1080|1280x720|2160p|1080p|720p|480p)\b", re.IGNORECASE)
_WXH_TO_P = {"3840x2160": "2160p", "1920x1080": "1080p", "1280x720": "720p"}
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
    re.compile(r"第\s*(?P<season>\d{1,2})\s*季"),
    re.compile(r"第\s*(?P<season>\d{1,2})\s*期"),
]
FALLBACK_EPISODE_RE = re.compile(r"(?:^|[\s\-_])(?P<episode>\d{1,4})(?:[Vv](?P<revision>\d))?(?=$|[\s\-_])")
SOURCE_PATTERNS = {
    "WEB-DL": re.compile(r"\bWEB[- ]?DL\b", re.IGNORECASE),
    "BLURAY": re.compile(r"\bBluRay\b", re.IGNORECASE),
    "WEBRip": re.compile(r"\bWEB[- ]?Rip\b", re.IGNORECASE),
}
HEVC_RE = re.compile(r"\b(?:hevc|x265|h[\s.]?265)\b", re.IGNORECASE)
BATCH_MARKER_RE = re.compile(r"\b(?:batch|complete|end)\b", re.IGNORECASE)
FREE_TEXT_RANGE_RE = re.compile(r"(?<![Ss])(?<!\d)(?P<start>\d{1,3})\s*[-~]\s*(?P<end>\d{1,3})(?!\d)")
DUAL_AUDIO_RE = re.compile(r"\bdual(?:[ -]?audio)?\b", re.IGNORECASE)
EXTERNAL_SUB_MARKERS = ("外挂", "外掛", "外挂字幕", "外掛字幕", "external")
EMBEDDED_SUB_MARKERS = ("chs", "cht", "简中", "簡中", "繁中", "内嵌", "內嵌", "中字", "简繁", "簡繁", "内封", "內封")
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


def _extract_episode_from_bracket(title: str) -> tuple[str | None, bool]:
    """Extract episode from dedicated bracket like [1165] or [13] (dmhy format)."""
    bracket_contents = re.findall(r"\[([^\]]*)\]", title)
    best_match: str | None = None
    is_range = False

    for content in bracket_contents:
        stripped = content.strip()
        range_match = re.match(r"^(\d{2,4})\s*[-~]\s*(\d{2,4})$", stripped)
        if range_match:
            is_range = True
            first = range_match.group(1)
            best_match = first.zfill(2)
            continue

        num_match = re.match(r"^(\d+)$", stripped)
        if not num_match:
            continue

        num = int(num_match.group(1))
        if 1900 <= num <= 2030 or num in (480, 720, 1080, 2160, 240, 360):
            continue

        candidate_val = str(num).zfill(2)

        if best_match is None or int(candidate_val) > int(best_match):
            best_match = candidate_val

    if best_match is None:
        return None, False

    has_season_bracket = any(
        re.match(r"^[Ss]\d{1,2}$", content.strip()) and content.strip() != f"S{best_match.lstrip('0')}"
        for content in bracket_contents
    )
    if has_season_bracket:
        return None, False

    return best_match, is_range


def _bracket_has_range(title: str) -> bool:
    for content in re.findall(r"\[([^\]]*)\]", title):
        if re.match(r"^\d{2,4}\s*[-~]\s*\d{2,4}$", content.strip()):
            return True
    return False


def _extract_episode(title: str) -> tuple[str | None, bool]:
    for pattern in EXPLICIT_EPISODE_PATTERNS:
        match = pattern.search(title)
        if match:
            episode = match.group("episode").zfill(2)
            return episode, bool(match.groupdict().get("revision"))

    bracket_episode, _ = _extract_episode_from_bracket(title)
    if bracket_episode is not None:
        return bracket_episode, False

    cleaned = _clean_title_for_episode_search(title)
    for match in FALLBACK_EPISODE_RE.finditer(cleaned):
        episode = match.group("episode")
        num = int(episode)
        if 1900 <= num <= 2030:
            continue
        return episode.zfill(2), bool(match.groupdict().get("revision"))
    return None, False


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
    bracket_text = " ".join(re.findall(r"\[([^\]]*)\]", title)).casefold()

    if any(marker in lowered or marker in bracket_text for marker in EXTERNAL_SUB_MARKERS):
        return "external"
    if any(marker in lowered or marker in bracket_text for marker in EMBEDDED_SUB_MARKERS):
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
        raw = resolution_match.group(1).lower()
        candidate.resolution = _WXH_TO_P.get(raw, raw)

    candidate.season = _extract_season(title)
    candidate.is_raw = any(marker in lower_title for marker in RAW_MARKERS)
    candidate.source_type = _extract_source_type(title)
    if candidate.source_type == "WEB-DL":
        candidate.is_raw = True

    free_text_range = FREE_TEXT_RANGE_RE.search(title)
    candidate.is_batch = (
        bool(BATCH_MARKER_RE.search(title)) or "合集" in title or _bracket_has_range(title) or bool(free_text_range)
    )
    candidate.is_hevc = bool(HEVC_RE.search(title))
    candidate.has_dual_audio = bool(DUAL_AUDIO_RE.search(title))
    if free_text_range:
        candidate.episode = free_text_range.group("start").zfill(2)
        candidate.is_v2 = bool(re.search(r"\bv[23]\b", lower_title))
    else:
        candidate.episode, range_or_revision = _extract_episode(title)
        candidate.is_v2 = range_or_revision or bool(re.search(r"\bv[23]\b", lower_title))
    candidate.subtitle_type = _extract_subtitle_type(title, candidate)
    candidate.parsed_title = _infer_parsed_title(title)

    return candidate
