from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from aqsd.config import AppConfig
from aqsd.discovery import SearchRequest, discover_search_candidates, resolve_search_title
from aqsd.models import Candidate, ScoreBreakdown, SearchDiagnostics
from aqsd.qbittorrent import QBittorrentClient


API_DEPENDENCY_ERROR = "API server dependencies are not installed. Please install fastapi and uvicorn."
DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8765
MAX_API_SEARCH_LIMIT = 100
WEB_DIR = Path(__file__).with_name("web")


class ResolveTitlePayload(BaseModel):
    query: str


class SearchPayload(BaseModel):
    query: str
    episode: str | None = None
    resolution: str | None = None
    subtitle: str | None = None
    group: str | None = None
    raw_only: bool = False
    exclude_batch: bool = False
    limit: int = 20


def create_api_app(config: AppConfig):
    fastapi, http_exception, file_response, plain_text_response = _import_fastapi_runtime()

    app = fastapi.FastAPI(title="aqsd API", version="0.1.0")

    @app.get("/")
    def index():
        return _web_file_response("index.html", media_type="text/html; charset=utf-8", file_response=file_response, http_exception=http_exception)

    @app.get("/app.js")
    def app_js():
        return _web_file_response("app.js", media_type="application/javascript; charset=utf-8", file_response=file_response, http_exception=http_exception)

    @app.get("/style.css")
    def style_css():
        return _web_file_response("style.css", media_type="text/css; charset=utf-8", file_response=file_response, http_exception=http_exception)

    @app.get("/favicon.ico")
    def favicon():
        return plain_text_response("", status_code=204)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return build_health_payload(config)

    @app.post("/api/resolve-title")
    def resolve_title(payload: ResolveTitlePayload) -> dict[str, Any]:
        query = payload.query.strip()
        if not query:
            raise http_exception(status_code=400, detail="query must not be empty")

        resolution = resolve_search_title(config, query)
        return {
            "query": query,
            "expanded_queries": resolution.expanded_queries,
            "sources": _serialize_title_resolution_sources(resolution),
        }

    @app.post("/api/search")
    def search(payload: SearchPayload) -> dict[str, Any]:
        query = payload.query.strip()
        if not query:
            raise http_exception(status_code=400, detail="query must not be empty")

        limit = max(1, min(int(payload.limit or 20), MAX_API_SEARCH_LIMIT))
        request = SearchRequest(
            query=query,
            episodes=[payload.episode] if payload.episode else [],
            resolution=payload.resolution,
            groups=[payload.group] if payload.group else [],
            subtitle_type=None if payload.subtitle in (None, "", "any") else payload.subtitle,
            raw_only=payload.raw_only,
            limit=limit,
        )
        result = discover_search_candidates(config, request)
        diagnostics = serialize_diagnostics(result.diagnostics)
        if payload.exclude_batch:
            diagnostics["active_filters"]["exclude_batch"] = True

        return {
            "query": query,
            "expanded_queries": list(result.diagnostics.expanded_queries if result.diagnostics else request.expanded_queries or [query]),
            "candidates": [serialize_candidate(candidate, rank=index) for index, candidate in enumerate(result.candidates, start=1)],
            "diagnostics": diagnostics,
        }

    return app


def run_server_command(config: AppConfig, *, host: str = DEFAULT_API_HOST, port: int = DEFAULT_API_PORT) -> int:
    try:
        _import_fastapi_runtime()
        uvicorn = _import_uvicorn_runtime()
    except RuntimeError as exc:
        print(str(exc))
        return 1

    app = create_api_app(config)
    print(f"Starting aqsd API server at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
    return 0


def build_health_payload(config: AppConfig) -> dict[str, Any]:
    qb_configured = bool(config.qb.base_url.strip())
    qb_status = _probe_qb_status(config) if qb_configured else {"configured": False, "reachable": False}
    payload = {
        "ok": bool(qb_status.get("reachable")),
        "qbittorrent": qb_status,
        "sources": {
            "rss": any(source.enabled for source in config.rss_sources),
            "nyaa": bool(config.search_sources.nyaa.enabled),
            "torznab": bool(
                config.search_sources.torznab.enabled
                and any(endpoint.enabled for endpoint in config.search_sources.torznab.endpoints)
            ),
        },
        "anilist": {
            "enabled": bool(config.metadata_sources.anilist.enabled),
        },
    }
    return payload


def serialize_candidate(candidate: Candidate, rank: int) -> dict[str, Any]:
    candidate_url = candidate.url or ""
    return {
        "rank": rank,
        "title": candidate.title,
        "score": candidate.score,
        "source": candidate.source,
        "seeders": candidate.seeders,
        "size": None,
        "published_at": _serialize_datetime(candidate.published_at),
        "magnet": candidate_url if candidate_url.casefold().startswith("magnet:") else None,
        "url": candidate_url or None,
        "parsed": {
            "episode": candidate.episode,
            "resolution": candidate.resolution,
            "group": candidate.group,
            "subtitle_type": candidate.subtitle_type,
            "is_batch": candidate.is_batch,
            "is_raw": candidate.is_raw,
        },
        "breakdown": serialize_breakdown(candidate.breakdown),
    }


def serialize_breakdown(breakdown: ScoreBreakdown | None) -> list[dict[str, Any]]:
    if breakdown is None:
        return []
    return [asdict(reason) for reason in breakdown.reasons]


def serialize_diagnostics(diagnostics: SearchDiagnostics | None) -> dict[str, Any]:
    if diagnostics is None:
        return {
            "original_query": "",
            "expanded_queries": [],
            "sources": [],
            "active_filters": {},
            "candidate_count_before_filter": None,
            "candidate_count_after_filter": None,
            "suggestions": [],
        }
    return {
        "original_query": diagnostics.original_query,
        "expanded_queries": list(diagnostics.expanded_queries),
        "sources": list(diagnostics.sources),
        "active_filters": dict(diagnostics.active_filters),
        "candidate_count_before_filter": diagnostics.candidate_count_before_filter,
        "candidate_count_after_filter": diagnostics.candidate_count_after_filter,
        "suggestions": list(diagnostics.suggestions),
    }


def _probe_qb_status(config: AppConfig) -> dict[str, Any]:
    client = QBittorrentClient(
        base_url=config.qb.base_url,
        username=config.qb.username,
        password=config.qb.password,
    )
    try:
        client.login()
        client.get_version()
    except Exception as exc:
        return {
            "configured": True,
            "reachable": False,
            "error": str(exc),
        }
    return {
        "configured": True,
        "reachable": True,
    }


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _serialize_title_resolution_sources(resolution: Any) -> list[str]:
    sources: list[str] = []
    if getattr(resolution, "local_alias_matched", False):
        sources.append("local_aliases")
    if getattr(resolution, "cache_hit", False):
        sources.append("cache")
    if getattr(resolution, "source", "") in {"anilist", "anilist-cache"} or getattr(resolution, "anilist_attempted", False):
        sources.append("anilist")
    if not sources:
        source = getattr(resolution, "source", "") or "query"
        sources.append(source)
    return sources


def _import_fastapi_runtime():
    try:
        import fastapi
        from fastapi import HTTPException
        from fastapi.responses import FileResponse, PlainTextResponse
    except ImportError as exc:  # pragma: no cover - depends on optional dependency
        raise RuntimeError(API_DEPENDENCY_ERROR) from exc
    return fastapi, HTTPException, FileResponse, PlainTextResponse


def _import_uvicorn_runtime():
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - depends on optional dependency
        raise RuntimeError(API_DEPENDENCY_ERROR) from exc
    return uvicorn


def _web_file_response(filename: str, *, media_type: str, file_response: Any, http_exception: Any):
    path = WEB_DIR / filename
    if not path.exists():
        raise http_exception(status_code=500, detail=f"missing web asset: {filename}")
    return file_response(path, media_type=media_type)
