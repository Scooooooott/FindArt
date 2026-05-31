from __future__ import annotations

from collections.abc import Sequence

from app.data.default_catalog import DEFAULT_CATALOG
from app.models import ArtworkCandidate, ArtworkImage
from app.services.museum import candidate_from_catalog


class ImageNotFoundError(LookupError):
    pass


class ImageResolver:
    def __init__(self, catalog: Sequence[dict] | None = None) -> None:
        self.catalog = list(catalog or DEFAULT_CATALOG)
        self._cache: dict[str, ArtworkImage] = {}

    async def resolve(
        self,
        candidate: ArtworkCandidate | None = None,
        source_api: str | None = None,
        artwork_id: str | None = None,
    ) -> ArtworkImage:
        resolved_candidate = candidate or self._find_candidate(source_api, artwork_id)
        if resolved_candidate is None:
            raise ImageNotFoundError("Artwork image could not be resolved.")

        cache_key = f"{resolved_candidate.source_api}:{resolved_candidate.id}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached.model_copy(update={"cached": True})

        image = self._build_image(resolved_candidate)
        self._cache[cache_key] = image
        return image

    def _find_candidate(
        self,
        source_api: str | None,
        artwork_id: str | None,
    ) -> ArtworkCandidate | None:
        if not source_api or not artwork_id:
            return None
        for item in self.catalog:
            if item["source_api"] == source_api and item["id"] == artwork_id:
                return candidate_from_catalog(item)
        return None

    def _build_image(self, candidate: ArtworkCandidate) -> ArtworkImage:
        if candidate.iiif_base_url:
            base = candidate.iiif_base_url.rstrip("/")
            return ArtworkImage(
                id=candidate.id,
                source_api=candidate.source_api,
                full_url=f"{base}/full/1600,/0/default.jpg",
                medium_url=f"{base}/full/800,/0/default.jpg",
                iiif_base_url=base,
                cached=False,
            )

        fallback = (
            candidate.image_url
            or candidate.thumbnail_url
            or "https://example.com/default-artworks/placeholder.jpg"
        )
        return ArtworkImage(
            id=candidate.id,
            source_api=candidate.source_api,
            full_url=fallback,
            medium_url=fallback,
            cached=False,
        )

