from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated, Any

from dotenv import load_dotenv

load_dotenv()  # Must run before any service reads env vars

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app import db as _db
from app.models import (
    AddFavouriteRequest,
    ArtworkImage,
    FavouritesResponse,
    HistoryResponse,
    LineartRequest,
    LineartResponse,
    PaletteRequest,
    PaletteResponse,
    ResolveImageRequest,
    SearchRequest,
    SearchResponse,
)
from app.services import session_service, style_transfer
from app.services.image_resolver import ImageNotFoundError, ImageResolver
from app.services.url_guard import validate_image_url
from app.services.museum import build_museum_search_service
from app.services.pipeline import SearchPipeline

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------

def _log_startup_env() -> None:
    """Emit a single INFO line summarising which env vars are present."""
    def _present(key: str) -> str:
        val = os.getenv(key, "").strip()
        if not val:
            return "MISSING"
        if "KEY" in key or "PASSWORD" in key or "SECRET" in key or "URL" in key:
            return f"SET({len(val)}chars)"
        return val

    logger.info(
        "Startup env — DEEPSEEK_API_KEY=%s  GEMINI_API_KEY=%s  "
        "FINDART_PROVIDERS=%s  QDRANT_URL=%s  QDRANT_API_KEY=%s  "
        "EMBEDDING_MODEL=%s  DATABASE_URL=%s",
        _present("DEEPSEEK_API_KEY"),
        _present("GEMINI_API_KEY"),
        _present("FINDART_PROVIDERS"),
        _present("QDRANT_URL"),
        _present("QDRANT_API_KEY"),
        _present("EMBEDDING_MODEL"),
        _present("DATABASE_URL"),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _log_startup_env()

    db_url = os.getenv("DATABASE_URL", "").strip()
    if db_url:
        try:
            app.state.db = await _db.create_pool()
        except Exception as exc:
            logger.warning("PostgreSQL unavailable (%s) — session features disabled", exc)
            app.state.db = None
    else:
        logger.info("DATABASE_URL not set — session features disabled")
        app.state.db = None

    yield

    if getattr(app.state, "db", None) is not None:
        await app.state.db.close()
        logger.info("PostgreSQL pool closed")


# ---------------------------------------------------------------------------
# App & middleware
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="FindArt Pipeline API", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(GZipMiddleware, minimum_size=500)
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
_allow_origins: list[str] = (
    [o.strip() for o in _raw_origins.split(",") if o.strip()]
    if _raw_origins.strip()
    else ["*"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,  # nosemgrep: wildcard-cors — defaults to * in dev; set ALLOWED_ORIGINS in production
    allow_methods=["*"],
    allow_headers=["*"],
)

pipeline = SearchPipeline(museum_search=build_museum_search_service(include_default=False))
image_resolver = ImageResolver()

# Vision pipeline — Gemini Vision for image-based search (shares museum/vector instances)
_vision_pipeline: SearchPipeline | None = None
_gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
if _gemini_key:
    try:
        from app.services.intent import LLMIntentParser as _LLMIntentParser
        _vision_intent = _LLMIntentParser(
            api_key=_gemini_key,
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        )
        _vision_pipeline = SearchPipeline(
            intent_parser=_vision_intent,
            museum_search=pipeline.museum_search,
            vector_search=pipeline.vector_search,
        )
        logger.info("Vision pipeline initialized (Gemini Vision)")
    except Exception as _exc:
        logger.warning("Vision pipeline unavailable: %s", _exc)


class _ImageSearchRequest(BaseModel):
    image_base64: str
    mime_type: str = "image/jpeg"
    limit: int = 8


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

def get_db(request: Request):
    """Return the asyncpg pool from app state, or None if DB is not configured."""
    return getattr(request.app.state, "db", None)


def get_session_id(x_session_id: str | None = Header(None)) -> str | None:
    """Extract and validate X-Session-ID header. Returns None if absent or malformed."""
    if x_session_id and session_service.is_valid_session_id(x_session_id):
        return x_session_id
    return None


async def _safe_task(coro) -> None:
    try:
        await coro
    except Exception as exc:
        logger.warning("Background task failed: %s", exc)


# Strong references prevent fire-and-forget tasks from being GC'd before completion.
_background_tasks: set[asyncio.Task] = set()


def _create_background_task(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


# ---------------------------------------------------------------------------
# Dependency type aliases  (Annotated pattern — FastAPI 0.95+ recommendation)
# ---------------------------------------------------------------------------

DbDep = Annotated[Any, Depends(get_db)]
SessionIdDep = Annotated[str | None, Depends(get_session_id)]

# Reusable responses dicts for OpenAPI documentation
_R_SESSION = {
    400: {"description": "Invalid or missing session ID"},
    503: {"description": "Session storage not configured (DATABASE_URL unset)"},
}
_R_STYLE = {
    502: {"description": "Failed to fetch image from upstream source"},
    503: {"description": "Style transfer dependency unavailable"},
}
_R_RESOLVE = {
    404: {"description": "Image could not be resolved for this artwork"},
}


# ---------------------------------------------------------------------------
# Core routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/search")
@limiter.limit("20/minute")
async def search(
    request: Request,
    body: SearchRequest,
    db: DbDep,
    session_id: SessionIdDep,
) -> SearchResponse:
    result = await pipeline.search(text=body.text, limit=body.limit)
    if db is not None and session_id:
        _create_background_task(_safe_task(session_service.upsert_session(db, session_id)))
        _create_background_task(_safe_task(session_service.log_search(
            db, session_id, body.text,
            result.query.model_dump(),
            len(result.candidates),
            result.diagnostics.fallback_mode,
        )))
    return result


@app.post("/search/stream")
@limiter.limit("20/minute")
async def search_stream(
    request: Request,
    body: SearchRequest,
    db: DbDep,
    session_id: SessionIdDep,
) -> StreamingResponse:
    async def generate():
        result_snapshot: dict = {}
        try:
            async for data in pipeline.search_stream(text=body.text, limit=body.limit):
                yield f"data: {data}\n\n"
                try:
                    event = json.loads(data)
                    if event.get("type") == "result":
                        result_snapshot = event
                except Exception:
                    pass
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

        # After stream completes: fire-and-forget session touch + history write
        if db is not None and session_id and result_snapshot:
            _create_background_task(_safe_task(
                session_service.upsert_session(db, session_id)
            ))
            _create_background_task(_safe_task(session_service.log_search(
                db,
                session_id,
                body.text,
                result_snapshot.get("query"),
                len(result_snapshot.get("candidates", [])),
                (result_snapshot.get("diagnostics") or {}).get("fallback_mode"),
            )))

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Image search route
# ---------------------------------------------------------------------------

@app.post("/search/image")
@limiter.limit("10/minute")
async def search_by_image(request: Request, body: _ImageSearchRequest) -> SearchResponse:
    """Search by uploaded image (Gemini Vision → ArtworkQuery → pipeline). Requires GEMINI_API_KEY."""
    if _vision_pipeline is None:
        raise HTTPException(
            status_code=503,
            detail="Image search requires GEMINI_API_KEY to be configured",
        )
    try:
        return await _vision_pipeline.search_image(body.image_base64, body.mime_type, body.limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Style transfer routes
# ---------------------------------------------------------------------------

@app.post("/artworks/palette", responses=_R_STYLE)
@limiter.limit("20/minute")
async def extract_palette(request: Request, body: PaletteRequest) -> PaletteResponse:
    validate_image_url(body.image_url)
    try:
        colors = await style_transfer.extract_palette(body.image_url, body.n_colors)
        return PaletteResponse(colors=colors)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Image fetch error: {exc.response.status_code}") from exc


@app.post("/artworks/lineart", responses=_R_STYLE)
@limiter.limit("10/minute")
async def generate_lineart(request: Request, body: LineartRequest) -> LineartResponse:
    validate_image_url(body.image_url)
    try:
        b64 = await style_transfer.generate_lineart(body.image_url, body.mode)
        return LineartResponse(lineart_b64=b64)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Image fetch error: {exc.response.status_code}") from exc


@app.post("/artworks/resolve-image", responses=_R_RESOLVE)
async def resolve_image(request: Request, body: ResolveImageRequest) -> ArtworkImage:
    try:
        return await image_resolver.resolve(
            candidate=body.candidate,
            source_api=body.source_api,
            artwork_id=body.id,
        )
    except ImageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Session routes
# ---------------------------------------------------------------------------

def _require_db(db) -> None:
    if db is None:
        raise HTTPException(status_code=503, detail="Session storage not configured (DATABASE_URL unset)")


def _require_valid_session(session_id: str) -> None:
    if not session_service.is_valid_session_id(session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID")


@app.get("/sessions/{session_id}/history", responses=_R_SESSION)
async def get_history(
    session_id: str,
    db: DbDep,
    limit: int = 20,
) -> HistoryResponse:
    _require_db(db)
    _require_valid_session(session_id)
    entries = await session_service.get_history(db, session_id, limit=min(limit, 50))
    return HistoryResponse(history=entries)


@app.delete("/sessions/{session_id}/history", status_code=204, responses=_R_SESSION)
async def clear_history(
    session_id: str,
    db: DbDep,
) -> None:
    _require_db(db)
    _require_valid_session(session_id)
    await session_service.clear_history(db, session_id)


@app.get("/sessions/{session_id}/favourites", responses=_R_SESSION)
async def get_favourites(
    session_id: str,
    db: DbDep,
) -> FavouritesResponse:
    _require_db(db)
    _require_valid_session(session_id)
    favs = await session_service.get_favourites(db, session_id)
    return FavouritesResponse(favourites=favs)


@app.post("/sessions/{session_id}/favourites", status_code=201, responses=_R_SESSION)
async def add_favourite(
    session_id: str,
    body: AddFavouriteRequest,
    db: DbDep,
) -> None:
    _require_db(db)
    _require_valid_session(session_id)
    await session_service.upsert_session(db, session_id)
    await session_service.add_favourite(db, session_id, body.candidate.model_dump())


@app.delete("/sessions/{session_id}/favourites/{artwork_id}/{source_api}", status_code=204, responses=_R_SESSION)
async def remove_favourite(
    session_id: str,
    artwork_id: str,
    source_api: str,
    db: DbDep,
) -> None:
    _require_db(db)
    _require_valid_session(session_id)
    await session_service.remove_favourite(db, session_id, artwork_id, source_api)


@app.delete("/sessions/{session_id}", status_code=204, responses=_R_SESSION)
async def delete_session(
    session_id: str,
    db: DbDep,
) -> None:
    _require_db(db)
    _require_valid_session(session_id)
    await session_service.delete_session(db, session_id)
