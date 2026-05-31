from __future__ import annotations

from collections.abc import Sequence

from app.data.default_catalog import DEFAULT_CATALOG
from app.models import ArtworkCandidate, ArtworkQuery
from app.services.museum import candidate_from_catalog, score_catalog_item


class DefaultVectorSearchService:
    """Local stand-in for Qdrant-backed vector retrieval."""

    name = "default_vector"

    def __init__(self, catalog: Sequence[dict] | None = None) -> None:
        self.catalog = list(catalog or DEFAULT_CATALOG)

    async def search(self, query: ArtworkQuery, limit: int) -> list[ArtworkCandidate]:
        scored = []
        for item in self.catalog:
            score = score_catalog_item(item, query)
            if score > 0:
                scored.append((score * 0.7, item))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            candidate_from_catalog(item, score=score, retrieval_path=self.name)
            for score, item in scored[:limit]
        ]

