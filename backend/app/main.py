from __future__ import annotations

from fastapi import FastAPI, HTTPException

from app.models import ArtworkImage, ResolveImageRequest, SearchRequest, SearchResponse
from app.services.image_resolver import ImageNotFoundError, ImageResolver
from app.services.museum import build_museum_search_service
from app.services.pipeline import SearchPipeline


app = FastAPI(title="FindArt Pipeline API", version="0.1.0")
pipeline = SearchPipeline(museum_search=build_museum_search_service())
image_resolver = ImageResolver()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse:
    return await pipeline.search(text=request.text, limit=request.limit)


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
