from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from aqsd.cart_service import CartService
from aqsd.cart_store import CartStore
from aqsd.config import AppConfig
from aqsd.discovery import SearchRequest, discover_search_candidates
from aqsd.models import Candidate, ExpandedQueryDetail, ScoreBreakdown, SearchDiagnostics, TitleEvidence
from aqsd.qbittorrent import QBittorrentAddTorrentError, QBittorrentClient
from aqsd.utils import fix_magnet_name


API_DEPENDENCY_ERROR = "API server dependencies are not installed. Please install fastapi and uvicorn."
DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8765
MAX_API_SEARCH_LIMIT = 100
WEB_DIR = Path(__file__).with_name("web")


class SearchPayload(BaseModel):
    query: str
    episode: str | None = None
    season: str | None = None
    resolution: str | None = None
    subtitle: str | None = None
    group: str | None = None
    raw_only: bool = False
    exclude_batch: bool = False
    batch_only: bool = False
    release_mode: str = Field(default="any", pattern="^(any|episode|batch)$")
    limit: int = 20


class DownloadPayload(BaseModel):
    url: str
    title: str | None = None
    category: str | None = None
    save_path: str | None = None


class CreateCartPayload(BaseModel):
    anime_name: str
    episode: str = ""
    items: list[dict[str, Any]] = Field(default_factory=list)


class AddCartItemsPayload(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)


def _build_qb_client(config: AppConfig) -> QBittorrentClient:
    client = QBittorrentClient(
        base_url=config.qb.base_url,
        username=config.qb.username,
        password=config.qb.password,
    )
    client.login()
    return client


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

    @app.post("/api/search")
    def search(payload: SearchPayload) -> dict[str, Any]:
        query = payload.query.strip()
        if not query:
            raise http_exception(status_code=400, detail="query must not be empty")

        limit = max(1, min(int(payload.limit or 20), MAX_API_SEARCH_LIMIT))
        release_mode = "batch" if payload.batch_only else payload.release_mode
        season = _parse_int(payload.season)
        request = SearchRequest(
            query=query,
            episodes=[payload.episode] if payload.episode else [],
            season=season,
            resolution=payload.resolution,
            groups=[payload.group] if payload.group else [],
            subtitle_type=None if payload.subtitle in (None, "", "any") else payload.subtitle,
            raw_only=payload.raw_only,
            exclude_batch=payload.exclude_batch,
            release_mode=release_mode,
            limit=limit,
        )
        result = discover_search_candidates(config, request)
        diagnostics = serialize_diagnostics(result.diagnostics)

        return {
            "query": query,
            "expanded_queries": list(result.diagnostics.expanded_queries if result.diagnostics else request.expanded_queries or [query]),
            "candidates": [serialize_candidate(candidate, rank=index) for index, candidate in enumerate(result.candidates, start=1)],
            "diagnostics": diagnostics,
        }

    @app.post("/api/download")
    def download(payload: DownloadPayload) -> dict[str, Any]:
        url = payload.url.strip()
        if not url:
            raise http_exception(status_code=400, detail="url must not be empty")

        _validate_qb_configured(config, http_exception)

        client = QBittorrentClient(
            base_url=config.qb.base_url,
            username=config.qb.username,
            password=config.qb.password,
        )
        try:
            client.login()
        except Exception as exc:
            raise http_exception(status_code=502, detail=f"qBittorrent 登录失败：{exc}")

        try:
            fixed_url = fix_magnet_name(url, payload.title)
            client.add_torrent(
                url=fixed_url,
                category=payload.category or config.qb.default_category,
                save_path=payload.save_path or config.qb.default_save_path,
                tags="aqsd",
            )
        except QBittorrentAddTorrentError as exc:
            raise http_exception(status_code=502, detail=str(exc))

        return {"ok": True, "title": payload.title}

    @app.get("/api/downloads")
    def downloads() -> dict[str, Any]:
        _validate_qb_configured(config, http_exception)

        client = QBittorrentClient(
            base_url=config.qb.base_url,
            username=config.qb.username,
            password=config.qb.password,
        )
        try:
            client.login()
        except Exception as exc:
            raise http_exception(status_code=502, detail=f"qBittorrent 登录失败：{exc}")

        try:
            torrents = client.list_torrents()
        except Exception as exc:
            raise http_exception(status_code=502, detail=f"获取下载列表失败：{exc}")

        return {"torrents": [_serialize_torrent(t) for t in torrents]}

    cart_store = CartStore(Path(config.app.database).parent / "carts.json")
    cart_service = CartService(cart_store, lambda: _build_qb_client(config))

    @app.post("/api/carts")
    def create_cart(payload: CreateCartPayload) -> dict[str, Any]:
        if not payload.anime_name.strip():
            raise http_exception(status_code=400, detail="anime_name must not be empty")
        if not payload.items:
            raise http_exception(status_code=400, detail="items must not be empty")
        cart = cart_service.create_cart(payload.anime_name.strip(), payload.episode.strip(), payload.items)
        return serialize_cart(cart)

    @app.get("/api/carts")
    def list_carts() -> dict[str, Any]:
        carts = cart_service.list_carts()
        return {"carts": [serialize_cart(c) for c in carts]}

    @app.get("/api/carts/{cart_id}")
    def get_cart(cart_id: str) -> dict[str, Any]:
        cart = cart_service.get_cart(cart_id)
        if cart is None:
            raise http_exception(status_code=404, detail="cart not found")
        return serialize_cart(cart)

    @app.post("/api/carts/{cart_id}/items")
    def add_cart_items(cart_id: str, payload: AddCartItemsPayload) -> dict[str, Any]:
        cart = cart_service.add_items(cart_id, payload.items)
        if cart is None:
            raise http_exception(status_code=404, detail="cart not found")
        return serialize_cart(cart)

    @app.post("/api/carts/{cart_id}/start")
    def start_cart(cart_id: str) -> dict[str, Any]:
        cart = cart_service.start_cart(cart_id)
        if cart is None:
            raise http_exception(status_code=400, detail="cart cannot be started")
        return serialize_cart(cart)

    @app.delete("/api/carts/{cart_id}")
    def delete_cart(cart_id: str) -> dict[str, Any]:
        ok = cart_service.delete_cart(cart_id)
        if not ok:
            raise http_exception(status_code=404, detail="cart not found")
        return {"ok": True}

    app.state.cart_service = cart_service
    return app


def run_server_command(config: AppConfig, *, host: str = DEFAULT_API_HOST, port: int = DEFAULT_API_PORT) -> int:
    try:
        _import_fastapi_runtime()
        uvicorn = _import_uvicorn_runtime()
    except RuntimeError as exc:
        print(str(exc))
        return 1

    app = create_api_app(config)
    try:
        cart_service = getattr(app.state, "cart_service", None)
        if cart_service is not None and config.qb.base_url.strip():
            cart_service.start_monitor()
            print("Cart monitor started")
    except Exception:
        pass
    print(f"Starting aqsd API server at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
    return 0


def build_health_payload(config: AppConfig) -> dict[str, Any]:
    qb_configured = bool(config.qb.base_url.strip())
    qb_status = _probe_qb_status(config) if qb_configured else {"configured": False, "reachable": False}
    return {
        "ok": bool(qb_status.get("reachable")),
        "qbittorrent": qb_status,
        "sources": {
            "rss": any(source.enabled for source in config.rss_sources),
        },
    }


def serialize_candidate(candidate: Candidate, rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "title": candidate.title,
        "score": candidate.score,
        "source": candidate.source,
        "seeders": candidate.seeders,
        "size": None,
        "published_at": _serialize_datetime(candidate.published_at),
        "magnet": candidate.magnet or None,
        "url": candidate.url or None,
        "info_hash": candidate.info_hash,
        "parsed": {
            "episode": candidate.episode,
            "season": candidate.season,
            "resolution": candidate.resolution,
            "group": candidate.group,
            "subtitle_type": candidate.subtitle_type,
            "is_batch": candidate.is_batch,
            "is_raw": candidate.is_raw,
        },
        "breakdown": serialize_breakdown(candidate.breakdown),
        "matched_query": candidate.matched_query,
        "matched_query_source": candidate.matched_query_source,
        "matched_query_subject_id": candidate.matched_query_subject_id,
        "matched_query_confidence": candidate.matched_query_confidence,
        "title_evidence": serialize_title_evidence(candidate.title_evidence),
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
            "expanded_query_details": [],
            "resolution_status": "unresolved",
            "needs_review": False,
            "sources": [],
            "active_filters": {},
            "candidate_count_before_filter": None,
            "candidate_count_after_filter": None,
            "stage_counts": {},
            "filter_drop_reasons": {},
            "suggestions": [],
            "resolved_subject": None,
            "candidate_subjects": [],
            "rejected_subjects": [],
        }
    return {
        "original_query": diagnostics.original_query,
        "expanded_queries": list(diagnostics.expanded_queries),
        "expanded_query_details": [serialize_expanded_query_detail(item) for item in diagnostics.expanded_query_details],
        "resolution_status": diagnostics.resolution_status,
        "needs_review": diagnostics.needs_review,
        "sources": list(diagnostics.sources),
        "active_filters": dict(diagnostics.active_filters),
        "candidate_count_before_filter": diagnostics.candidate_count_before_filter,
        "candidate_count_after_filter": diagnostics.candidate_count_after_filter,
        "stage_counts": dict(diagnostics.stage_counts),
        "filter_drop_reasons": dict(diagnostics.filter_drop_reasons),
        "suggestions": list(diagnostics.suggestions),
        "resolved_subject": serialize_resolved_subject(diagnostics.resolved_subject),
        "candidate_subjects": list(diagnostics.candidate_subjects),
        "rejected_subjects": list(diagnostics.rejected_subjects),
    }


def serialize_expanded_query_detail(detail: ExpandedQueryDetail) -> dict[str, Any]:
    return asdict(detail)


def serialize_resolved_subject(subject: Any) -> dict[str, Any] | None:
    if subject is None:
        return None
    return asdict(subject)


def serialize_title_evidence(evidence: TitleEvidence | None) -> dict[str, Any] | None:
    if evidence is None:
        return None
    return asdict(evidence)


def serialize_cart(cart: Any) -> dict[str, Any]:
    return {
        "cart_id": cart.cart_id,
        "anime_name": cart.anime_name,
        "episode": cart.episode,
        "items": [asdict(item) for item in cart.items],
        "tried_hashes": list(cart.tried_hashes),
        "active_hash": cart.active_hash,
        "active_title": cart.active_title,
        "fallback_count": cart.fallback_count,
        "max_fallbacks": cart.max_fallbacks,
        "status": cart.status,
        "events": [asdict(event) for event in cart.events],
        "created_at": cart.created_at,
    }


def _validate_qb_configured(config: AppConfig, http_exception: Any) -> None:
    if not config.qb.base_url.strip():
        raise http_exception(status_code=503, detail="qBittorrent 未配置，请先设置 base_url。")


def _serialize_torrent(torrent: dict[str, Any]) -> dict[str, Any]:
    return {
        "hash": torrent.get("hash", ""),
        "name": torrent.get("name", ""),
        "size": torrent.get("size"),
        "progress": torrent.get("progress"),
        "state": torrent.get("state"),
        "dlspeed": torrent.get("dlspeed"),
        "eta": torrent.get("eta"),
        "category": torrent.get("category"),
        "tags": torrent.get("tags", ""),
        "added_on": torrent.get("added_on"),
        "completion_on": torrent.get("completion_on"),
        "save_path": torrent.get("save_path"),
    }


def _probe_qb_status(config: AppConfig) -> dict[str, Any]:
    def _probe() -> dict[str, Any]:
        client = QBittorrentClient(
            base_url=config.qb.base_url,
            username=config.qb.username,
            password=config.qb.password,
        )
        try:
            client.login()
        except Exception as exc:
            return {"configured": True, "reachable": False, "error": f"login: {exc}"}
        try:
            client.get_version()
        except Exception as exc:
            return {"configured": True, "reachable": False, "error": f"version: {exc}"}
        return {"configured": True, "reachable": True}

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_probe)
        try:
            return future.result(timeout=5)
        except FutureTimeoutError:
            return {"configured": True, "reachable": False, "error": "health check timed out"}
        except Exception as exc:
            return {"configured": True, "reachable": False, "error": str(exc)}


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError:
        return None


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
    return file_response(path, media_type=media_type, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
