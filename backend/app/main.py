from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()  # Must run before any service reads env vars

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
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
from app.services.museum import build_museum_search_service
from app.services.pipeline import SearchPipeline

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to specific domains before production
    allow_methods=["*"],
    allow_headers=["*"],
)

pipeline = SearchPipeline(museum_search=build_museum_search_service(include_default=False))
image_resolver = ImageResolver()


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


# ---------------------------------------------------------------------------
# Core routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/search", response_model=SearchResponse)
@limiter.limit("20/minute")
async def search(
    request: Request,
    body: SearchRequest,
    db=Depends(get_db),
    session_id: str | None = Depends(get_session_id),
) -> SearchResponse:
    result = await pipeline.search(text=body.text, limit=body.limit)
    if db is not None and session_id:
        asyncio.create_task(_safe_task(session_service.upsert_session(db, session_id)))
        asyncio.create_task(_safe_task(session_service.log_search(
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
    db=Depends(get_db),
    session_id: str | None = Depends(get_session_id),
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
            asyncio.create_task(_safe_task(
                session_service.upsert_session(db, session_id)
            ))
            asyncio.create_task(_safe_task(session_service.log_search(
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
# Style transfer routes
# ---------------------------------------------------------------------------

@app.post("/artworks/palette", response_model=PaletteResponse)
@limiter.limit("20/minute")
async def extract_palette(request: Request, body: PaletteRequest) -> PaletteResponse:
    try:
        colors = await style_transfer.extract_palette(body.image_url, body.n_colors)
        return PaletteResponse(colors=colors)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Image fetch error: {exc.response.status_code}") from exc


@app.post("/artworks/lineart", response_model=LineartResponse)
@limiter.limit("10/minute")
async def generate_lineart(request: Request, body: LineartRequest) -> LineartResponse:
    try:
        b64 = await style_transfer.generate_lineart(body.image_url, body.mode)
        return LineartResponse(lineart_b64=b64)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Image fetch error: {exc.response.status_code}") from exc


@app.post("/artworks/resolve-image", response_model=ArtworkImage)
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


@app.get("/sessions/{session_id}/history", response_model=HistoryResponse)
async def get_history(
    session_id: str,
    limit: int = 20,
    db=Depends(get_db),
) -> HistoryResponse:
    _require_db(db)
    _require_valid_session(session_id)
    entries = await session_service.get_history(db, session_id, limit=min(limit, 50))
    return HistoryResponse(history=entries)


@app.delete("/sessions/{session_id}/history", status_code=204)
async def clear_history(
    session_id: str,
    db=Depends(get_db),
) -> None:
    _require_db(db)
    _require_valid_session(session_id)
    await session_service.clear_history(db, session_id)


@app.get("/sessions/{session_id}/favourites", response_model=FavouritesResponse)
async def get_favourites(
    session_id: str,
    db=Depends(get_db),
) -> FavouritesResponse:
    _require_db(db)
    _require_valid_session(session_id)
    favs = await session_service.get_favourites(db, session_id)
    return FavouritesResponse(favourites=favs)


@app.post("/sessions/{session_id}/favourites", status_code=201)
async def add_favourite(
    session_id: str,
    body: AddFavouriteRequest,
    db=Depends(get_db),
) -> None:
    _require_db(db)
    _require_valid_session(session_id)
    await session_service.upsert_session(db, session_id)
    await session_service.add_favourite(db, session_id, body.candidate.model_dump())


@app.delete("/sessions/{session_id}/favourites/{artwork_id}/{source_api}", status_code=204)
async def remove_favourite(
    session_id: str,
    artwork_id: str,
    source_api: str,
    db=Depends(get_db),
) -> None:
    _require_db(db)
    _require_valid_session(session_id)
    await session_service.remove_favourite(db, session_id, artwork_id, source_api)


@app.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    db=Depends(get_db),
) -> None:
    _require_db(db)
    _require_valid_session(session_id)
    await session_service.delete_session(db, session_id)
