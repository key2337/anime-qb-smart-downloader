from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol

from loguru import logger

from aqsd.config import ProbePolicy
from aqsd.models import Candidate
from aqsd.qbittorrent import QBittorrentClient
from aqsd.utils import build_task_tag, fix_magnet_name


class SleepFn(Protocol):
    def __call__(self, seconds: float) -> None:
        ...


@dataclass(slots=True)
class ProbeAttempt:
    candidate: Candidate
    tag: str
    initial_progress: float = 0.0


@dataclass(slots=True)
class ProbeResult:
    selected: Candidate | None
    selected_tag: str | None
    attempts: list[ProbeAttempt]
    scores: dict[str, float]


def probe_candidates(
    candidates: list[Candidate],
    qb: QBittorrentClient,
    policy: ProbePolicy,
    *,
    sleep_fn: SleepFn = time.sleep,
) -> ProbeResult:
    attempts: list[ProbeAttempt] = []
    scores: dict[str, float] = {}

    for candidate in candidates[: policy.max_candidates]:
        tag = build_task_tag(candidate.anime_name or "probe", candidate.episode or "00")
        try:
            download_url = fix_magnet_name(candidate.magnet or candidate.url, candidate.title)
            qb.add_torrent(
                download_url,
                category=candidate.category,
                save_path=candidate.save_path,
                tags=tag,
                paused=True,
            )
        except Exception as exc:
            logger.warning("Probe add failed for {}: {}", candidate.title, exc)
            continue
        attempts.append(ProbeAttempt(candidate=candidate, tag=tag))

    if not attempts:
        return ProbeResult(selected=None, selected_tag=None, attempts=[], scores={})

    # Batch resume probe torrents to avoid metaDL queue blocking
    time.sleep(2)
    by_tag = _list_torrents_by_tag(qb)
    probe_hashes: list[str] = []
    for attempt in attempts:
        t = by_tag.get(attempt.tag)
        if t and t.get("hash"):
            probe_hashes.append(t["hash"])
    if probe_hashes:
        try:
            qb.resume_torrents("|".join(probe_hashes))
        except Exception as exc:
            logger.warning("Probe batch resume failed: {}", exc)

    _capture_initial_progress(qb, attempts)
    sleep_fn(policy.duration_seconds)

    torrents = _list_torrents_by_tag(qb)
    selected_attempt: ProbeAttempt | None = None
    selected_score = float("-inf")

    for attempt in attempts:
        torrent = torrents.get(attempt.tag)
        if torrent is None:
            scores[attempt.tag] = 0.0
            continue

        score = calculate_probe_score(
            torrent,
            min_speed_kbps=policy.min_speed_kbps,
            initial_progress=attempt.initial_progress,
        )
        scores[attempt.tag] = score
        if score > selected_score:
            selected_score = score
            selected_attempt = attempt

    if policy.delete_losers:
        _delete_losers(qb, attempts, selected_attempt, torrents)

    return ProbeResult(
        selected=selected_attempt.candidate if selected_attempt else None,
        selected_tag=selected_attempt.tag if selected_attempt else None,
        attempts=attempts,
        scores=scores,
    )


def calculate_probe_score(
    torrent: dict,
    *,
    min_speed_kbps: int,
    initial_progress: float = 0.0,
) -> float:
    speed_kbps = float(torrent.get("dlspeed", 0) or 0) / 1024
    connected_seeds = int(torrent.get("num_seeds", 0) or 0)
    peers = int(torrent.get("num_leechs", torrent.get("num_peers", 0)) or 0)
    availability = float(torrent.get("availability", 0) or 0)
    progress = float(torrent.get("progress", 0) or 0)
    progress_delta = max(progress - initial_progress, 0.0)

    speed_score = speed_kbps if speed_kbps >= min_speed_kbps else speed_kbps * 0.1
    return speed_score + connected_seeds * 10 + peers * 2 + availability * 5 + progress_delta * 100_000


def _capture_initial_progress(qb: QBittorrentClient, attempts: list[ProbeAttempt]) -> None:
    torrents = _list_torrents_by_tag(qb)
    for attempt in attempts:
        torrent = torrents.get(attempt.tag)
        if torrent is not None:
            attempt.initial_progress = float(torrent.get("progress", 0) or 0)


def _list_torrents_by_tag(qb: QBittorrentClient) -> dict[str, dict]:
    by_tag: dict[str, dict] = {}
    for torrent in qb.list_torrents():
        raw_tags = torrent.get("tags", "") or ""
        for tag in [value.strip() for value in raw_tags.split(",") if value.strip()]:
            by_tag[tag] = torrent
    return by_tag


def _delete_losers(
    qb: QBittorrentClient,
    attempts: list[ProbeAttempt],
    selected_attempt: ProbeAttempt | None,
    torrents: dict[str, dict],
) -> None:
    selected_tag = selected_attempt.tag if selected_attempt else None
    for attempt in attempts:
        if attempt.tag == selected_tag:
            continue
        torrent = torrents.get(attempt.tag)
        torrent_hash = torrent.get("hash") if torrent else None
        if not torrent_hash:
            continue
        try:
            qb.delete_torrent(torrent_hash, delete_files=True)
        except Exception as exc:
            logger.warning("Probe loser delete failed for {}: {}", attempt.candidate.title, exc)
