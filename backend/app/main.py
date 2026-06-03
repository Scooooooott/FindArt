from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()  # Must run before any service reads env vars

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import httpx

from app.models import ArtworkImage, LineartRequest, LineartResponse, PaletteRequest, PaletteResponse, ResolveImageRequest, SearchRequest, SearchResponse
from app.services import style_transfer
from app.services.image_resolver import ImageNotFoundError, ImageResolver
from app.services.museum import build_museum_search_service
from app.services.pipeline import SearchPipeline


app = FastAPI(title="FindArt Pipeline API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to specific domains before production
    allow_methods=["*"],
    allow_headers=["*"],
)
pipeline = SearchPipeline(museum_search=build_museum_search_service(include_default=False))
image_resolver = ImageResolver()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse:
    return await pipeline.search(text=request.text, limit=request.limit)


@app.post("/artworks/palette", response_model=PaletteResponse)
async def extract_palette(request: PaletteRequest) -> PaletteResponse:
    try:
        colors = await style_transfer.extract_palette(request.image_url, request.n_colors)
        return PaletteResponse(colors=colors)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Image fetch error: {exc.response.status_code}") from exc


@app.post("/artworks/lineart", response_model=LineartResponse)
async def generate_lineart(request: LineartRequest) -> LineartResponse:
    try:
        b64 = await style_transfer.generate_lineart(request.image_url, request.mode)
        return LineartResponse(lineart_b64=b64)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Image fetch error: {exc.response.status_code}") from exc


@app.post("/artworks/resolve-image", response_model=ArtworkImage)
async def resolve_image(request: ResolveImageRequest) -> ArtworkImage:
    try:
        return await image_resolver.resolve(
            candidate=request.candidate,
            source_api=request.source_api,
            artwork_id=request.id,
        )
    except ImageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
