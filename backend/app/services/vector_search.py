from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Protocol

from app.models import ArtworkCandidate, ArtworkQuery
from app.services.museum import candidate_from_catalog

logger = logging.getLogger(__name__)

COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "artworks_e5large")

# intfloat/multilingual-e5-large (and the broader E5 family) requires
# "passage: " prefix for documents and "query: " prefix for queries.
# Leave both empty for MiniLM or other models without instruction prefixes.
_DOC_PREFIX   = os.getenv("EMBED_DOC_PREFIX",   "").strip()
_QUERY_PREFIX = os.getenv("EMBED_QUERY_PREFIX",  "").strip()


# ---------------------------------------------------------------------------
# Protocol — lets pipeline accept any vector search implementation
# ---------------------------------------------------------------------------

class VectorSearchService(Protocol):
    name: str
    async def search(self, query: ArtworkQuery, limit: int, score_threshold: float = 0.3) -> list[ArtworkCandidate]: ...


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _candidate_to_embed_text(candidate: ArtworkCandidate) -> str:
    """Convert an ArtworkCandidate to a single string for embedding."""
    parts: list[str] = []
    if candidate.title:
        parts.append(candidate.title)
    if candidate.artist:
        parts.append(f"by {candidate.artist}")
    if candidate.year:
        parts.append(str(candidate.year))
    if candidate.medium:
        parts.append(candidate.medium)
    # Enrich with style metadata populated by Wikidata / catalog ingest
    movement = candidate.metadata.get("movement")
    genre    = candidate.metadata.get("genre")
    if movement:
        parts.append(movement)
    if genre:
        parts.append(genre)
    return ". ".join(filter(None, parts))


def _artwork_to_embed_text(item: dict[str, Any]) -> str:
    """Convert a catalog dict to a single string for embedding."""
    parts: list[str] = []
    if item.get("title"):
        parts.append(item["title"])
    if item.get("artist"):
        parts.append(f"by {item['artist']}")
    if item.get("year"):
        parts.append(str(item["year"]))
    if item.get("medium"):
        parts.append(item["medium"])
    if item.get("style"):
        parts.append(item["style"])
    if item.get("period"):
        parts.append(item["period"])
    keywords = item.get("keywords") or []
    if keywords:
        parts.append(", ".join(keywords))
    return ". ".join(filter(None, parts))


def _query_to_embed_text(query: ArtworkQuery) -> str:
    """Convert an ArtworkQuery to a search string for embedding."""
    parts: list[str] = []
    if query.title:
        parts.append(query.title)
    if query.artist:
        parts.append(query.artist)
    if query.style:
        parts.append(query.style)
    if query.medium:
        parts.append(query.medium)
    if query.keywords:
        parts.append(" ".join(query.keywords))
    return " ".join(filter(None, parts)) or query.raw_text


def _stable_point_id(candidate: ArtworkCandidate) -> str:
    """Deterministic Qdrant point ID stable across ingest sources.

    Prioritises wikidata_id so the same painting ingested from Wikidata,
    Met, Rijksmuseum, etc. always maps to the same point — Qdrant upsert
    then overwrites rather than creating a duplicate vector.
    """
    key = candidate.wikidata_id or candidate.commons_filename or candidate.id
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, key))


# ---------------------------------------------------------------------------
# Qdrant-backed implementation
# ---------------------------------------------------------------------------

class QdrantVectorSearchService:
    name = "qdrant_vector"

    def __init__(self, client: Any, model_name: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers not installed. Run: pip install sentence-transformers"
            ) from exc

        self._client = client
        self._model = SentenceTransformer(model_name)
        self._dim = self._model.get_sentence_embedding_dimension()
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        from qdrant_client.models import Distance, VectorParams
        try:
            info = self._client.get_collection(COLLECTION_NAME)
            existing_dim = info.config.params.vectors.size
            if existing_dim == self._dim:
                return
            if os.getenv("QDRANT_ALLOW_REBUILD", "false").lower() != "true":
                raise RuntimeError(
                    f"Qdrant collection '{COLLECTION_NAME}' has dim={existing_dim} but "
                    f"model outputs dim={self._dim}. Set QDRANT_ALLOW_REBUILD=true to "
                    "permit rebuild (destructive — all vectors will be lost)."
                )
            logger.warning(
                "Collection '%s' has dim=%d but model outputs dim=%d — "
                "dropping and recreating (QDRANT_ALLOW_REBUILD=true). Re-run the ingest scripts.",
                COLLECTION_NAME, existing_dim, self._dim,
            )
            self._client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass  # collection does not exist yet
        self._client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=self._dim, distance=Distance.COSINE),
        )

    def seed_from_catalog(self, catalog: list[dict[str, Any]]) -> int:
        """Embed and upsert catalog items into Qdrant. Returns number of items indexed."""
        from qdrant_client.models import PointStruct

        if not catalog:
            return 0

        texts = [_DOC_PREFIX + _artwork_to_embed_text(item) for item in catalog]
        vectors = self._model.encode(texts, show_progress_bar=False).tolist()

        points = []
        for item, vector in zip(catalog, vectors):
            candidate = candidate_from_catalog(item, score=0.0, retrieval_path=self.name)
            points.append(PointStruct(
                id=_stable_point_id(candidate),
                vector=vector,
                payload=candidate.model_dump(),
            ))

        self._client.upsert(collection_name=COLLECTION_NAME, points=points)
        return len(points)

    def seed_from_candidates(self, candidates: list[ArtworkCandidate]) -> int:
        """Embed and upsert ArtworkCandidate objects directly. Returns number upserted."""
        from qdrant_client.models import PointStruct

        if not candidates:
            return 0

        texts = [_DOC_PREFIX + _candidate_to_embed_text(c) for c in candidates]
        vectors = self._model.encode(texts, show_progress_bar=False).tolist()

        points = []
        for candidate, vector in zip(candidates, vectors):
            points.append(PointStruct(
                id=_stable_point_id(candidate),
                vector=vector,
                payload=candidate.model_dump(),
            ))

        self._client.upsert(collection_name=COLLECTION_NAME, points=points)
        return len(points)

    async def search(self, query: ArtworkQuery, limit: int, score_threshold: float = 0.3) -> list[ArtworkCandidate]:
        import asyncio
        return await asyncio.to_thread(self._sync_search, query, limit, score_threshold)

    def _sync_search(self, query: ArtworkQuery, limit: int, score_threshold: float) -> list[ArtworkCandidate]:
        query_text = _QUERY_PREFIX + _query_to_embed_text(query)
        query_vector = self._model.encode(query_text).tolist()

        results = self._client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            limit=limit,
            score_threshold=score_threshold,
        ).points

        candidates: list[ArtworkCandidate] = []
        for result in results:
            try:
                payload = dict(result.payload)
                payload["score"] = float(result.score)
                payload["matched_sources"] = [self.name]
                candidates.append(ArtworkCandidate.model_validate(payload))
            except Exception as exc:
                logger.warning("Failed to reconstruct candidate from Qdrant payload: %s", exc)
        return candidates


# ---------------------------------------------------------------------------
# Rule-based fallback (original implementation, preserved)
# ---------------------------------------------------------------------------

class DefaultVectorSearchService:
    """Keyword-scoring stand-in used when Qdrant is unavailable."""

    name = "default_vector"

    def __init__(self, catalog: list[dict] | None = None) -> None:
        from app.data.default_catalog import DEFAULT_CATALOG
        self.catalog = list(catalog or DEFAULT_CATALOG)

    async def search(self, query: ArtworkQuery, limit: int, score_threshold: float = 0.3) -> list[ArtworkCandidate]:
        from app.services.museum import score_catalog_item

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


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_vector_search_service() -> QdrantVectorSearchService | DefaultVectorSearchService:
    """Return QdrantVectorSearchService if dependencies are available, else the fallback."""
    try:
        from qdrant_client import QdrantClient
    except ImportError:
        logger.info("qdrant-client not installed — using keyword-based vector search fallback")
        return DefaultVectorSearchService()

    model_name = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2").strip()
    qdrant_url = os.getenv("QDRANT_URL", "").strip()
    qdrant_api_key = os.getenv("QDRANT_API_KEY", "").strip() or None

    try:
        if qdrant_url:
            client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
            logger.info("Connecting to Qdrant at %s", qdrant_url)
        else:
            client = QdrantClient(":memory:")
            logger.info("Using in-memory Qdrant (data will not persist across restarts)")

        service = QdrantVectorSearchService(client=client, model_name=model_name)

        count = client.count(collection_name=COLLECTION_NAME).count
        if count == 0 and os.getenv("FINDART_SEED_CATALOG", "").lower() in ("1", "true", "yes"):
            from app.data.default_catalog import DEFAULT_CATALOG
            n = service.seed_from_catalog(list(DEFAULT_CATALOG))
            logger.info("Auto-seeded Qdrant with %d items from DEFAULT_CATALOG", n)
        else:
            logger.info(
                "Qdrant collection has %d existing points (seed skipped unless FINDART_SEED_CATALOG=true)",
                count,
            )

        return service

    except Exception as exc:
        logger.warning("Qdrant setup failed (%s) — falling back to keyword-based search", exc)
        return DefaultVectorSearchService()
