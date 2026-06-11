from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

from app.models import (
    ArtworkCandidate,
    ArtworkQuery,
    ClarificationHint,
    SearchDiagnostics,
    SearchResponse,
)
from app.services.aggregation import aggregate_candidates
from app.services.intent import IntentParser, create_intent_parser
from app.services.museum import MuseumSearchService
from app.services.vector_search import (
    VectorSearchService,
    create_vector_search_service,
)

# Minimum candidate count before each fallback strategy activates
_THRESHOLD_RELAX    = 3   # fewer than this → try relaxed vector threshold
_THRESHOLD_RESTRICT = 2   # fewer than this → try field-restricted query
_THRESHOLD_SPLIT    = 1   # fewer than this → try keyword split


class SearchPipeline:
    def __init__(
        self,
        intent_parser: IntentParser | None = None,
        museum_search: MuseumSearchService | None = None,
        vector_search: VectorSearchService | None = None,
    ) -> None:
        self.intent_parser = intent_parser or create_intent_parser()
        self.museum_search = museum_search or MuseumSearchService()
        self.vector_search = vector_search or create_vector_search_service()

    async def search(self, text: str, limit: int = 8) -> SearchResponse:
        request_id = str(uuid.uuid4())
        timings: dict[str, float] = {}

        t0 = time.perf_counter()
        query = await self.intent_parser.parse(text)
        timings["intent_ms"] = _elapsed_ms(t0)

        t1 = time.perf_counter()
        candidates, fallback_mode, warnings = await self._retrieve(query, limit)
        timings["retrieval_ms"] = _elapsed_ms(t1)
        timings["total_ms"] = _elapsed_ms(t0)

        clarification = _make_clarification(query, candidates)
        diagnostics = SearchDiagnostics(
            request_id=request_id,
            timings_ms=timings,
            providers=[*self.museum_search.provider_names, self.vector_search.name],
            warnings=warnings,
            fallback_mode=fallback_mode,
        )
        return SearchResponse(
            request_id=request_id,
            query=query,
            candidates=candidates,
            diagnostics=diagnostics,
            clarification=clarification,
        )

    async def search_image(self, image_base64: str, mime_type: str, limit: int = 8) -> SearchResponse:
        """Search by uploaded image. Requires LLMIntentParser (GEMINI_API_KEY)."""
        parse_image_fn = getattr(self.intent_parser, 'parse_image', None)
        if parse_image_fn is None:
            raise RuntimeError(
                "Image search requires a vision-capable intent parser. Set GEMINI_API_KEY."
            )
        request_id = str(uuid.uuid4())
        timings: dict[str, float] = {}

        t0 = time.perf_counter()
        query = await parse_image_fn(image_base64, mime_type)
        timings["intent_ms"] = _elapsed_ms(t0)

        t1 = time.perf_counter()
        candidates, fallback_mode, warnings = await self._retrieve(query, limit)
        timings["retrieval_ms"] = _elapsed_ms(t1)
        timings["total_ms"] = _elapsed_ms(t0)

        clarification = _make_clarification(query, candidates)
        diagnostics = SearchDiagnostics(
            request_id=request_id,
            timings_ms=timings,
            providers=[*self.museum_search.provider_names, self.vector_search.name],
            warnings=warnings,
            fallback_mode=fallback_mode,
        )
        return SearchResponse(
            request_id=request_id,
            query=query,
            candidates=candidates,
            diagnostics=diagnostics,
            clarification=clarification,
        )

    async def search_stream(self, text: str, limit: int = 8) -> AsyncIterator[str]:
        """Async generator yielding SSE data strings.

        Yields two events:
          {"type": "intent",  "query": {...}}          — after M1 completes
          {"type": "result",  "candidates": [...], ...} — after M2+M3 complete
        """
        request_id = str(uuid.uuid4())

        t0 = time.perf_counter()
        query = await self.intent_parser.parse(text)
        timings: dict[str, float] = {"intent_ms": _elapsed_ms(t0)}

        yield json.dumps({"type": "intent", "query": query.model_dump()})

        t1 = time.perf_counter()
        candidates, fallback_mode, warnings = await self._retrieve(query, limit)
        timings["retrieval_ms"] = _elapsed_ms(t1)
        timings["total_ms"] = _elapsed_ms(t0)

        clarification = _make_clarification(query, candidates)
        diagnostics = SearchDiagnostics(
            request_id=request_id,
            timings_ms=timings,
            providers=[*self.museum_search.provider_names, self.vector_search.name],
            warnings=warnings,
            fallback_mode=fallback_mode,
        )
        response = SearchResponse(
            request_id=request_id,
            query=query,
            candidates=candidates,
            diagnostics=diagnostics,
            clarification=clarification,
        )
        yield json.dumps({"type": "result", **response.model_dump()})

    async def _retrieve(
        self, query: ArtworkQuery, limit: int
    ) -> tuple[list[ArtworkCandidate], str | None, list[str]]:
        """M2 + M3 + fallbacks. Returns (candidates, fallback_mode, warnings)."""
        warnings: list[str] = []
        fallback_mode: str | None = None

        museum_task = asyncio.create_task(
            _safe(self.museum_search.search(query, limit=limit))
        )
        vector_task = asyncio.create_task(
            _safe(self.vector_search.search(query, limit=limit, score_threshold=0.3))
        )
        museum_raw, vector_raw = await asyncio.gather(museum_task, vector_task)

        if isinstance(museum_raw, Exception):
            warnings.append(f"museum_search_failed:{museum_raw}")
            logger.warning("[pipeline] museum_search raised: %s", museum_raw, exc_info=museum_raw)
            museum_candidates: list[ArtworkCandidate] = []
        else:
            museum_candidates = museum_raw
            warnings.extend(self.museum_search.last_warnings)

        if isinstance(vector_raw, Exception):
            logger.warning("[pipeline] vector_search raised: %s", vector_raw, exc_info=vector_raw)
        vector_candidates: list[ArtworkCandidate] = (
            vector_raw if not isinstance(vector_raw, Exception) else []
        )

        candidates = aggregate_candidates([museum_candidates, vector_candidates], limit=limit)
        logger.info(
            "[pipeline] initial retrieval: museum=%d vector=%d merged=%d",
            len(museum_candidates), len(vector_candidates), len(candidates),
        )

        if len(candidates) < _THRESHOLD_RELAX:
            logger.info("[pipeline] fallback relaxed_threshold (candidates=%d < %d)", len(candidates), _THRESHOLD_RELAX)
            relaxed_raw = await _safe(
                self.vector_search.search(query, limit=limit, score_threshold=0.15)
            )
            relaxed = relaxed_raw if not isinstance(relaxed_raw, Exception) else []
            merged = aggregate_candidates([museum_candidates, relaxed], limit=limit)
            if len(merged) > len(candidates):
                candidates = merged
                fallback_mode = "relaxed_threshold"
                logger.info("[pipeline] relaxed_threshold improved results to %d", len(candidates))

        if len(candidates) < _THRESHOLD_RESTRICT:
            logger.info("[pipeline] fallback field_restricted (candidates=%d < %d)", len(candidates), _THRESHOLD_RESTRICT)
            restricted_q = _restrict_query(query)
            restricted_raw = await _safe(
                self.vector_search.search(restricted_q, limit=limit, score_threshold=0.2)
            )
            restricted = restricted_raw if not isinstance(restricted_raw, Exception) else []
            merged = aggregate_candidates([museum_candidates, restricted], limit=limit)
            if len(merged) > len(candidates):
                candidates = merged
                fallback_mode = "field_restricted"
                logger.info("[pipeline] field_restricted improved results to %d", len(candidates))

        if len(candidates) < _THRESHOLD_SPLIT:
            logger.info("[pipeline] fallback keyword_split (candidates=%d < %d)", len(candidates), _THRESHOLD_SPLIT)
            split = await self._keyword_split_retrieve(query, museum_candidates, limit)
            if len(split) > len(candidates):
                candidates = split
                fallback_mode = "keyword_split"
                logger.info("[pipeline] keyword_split improved results to %d", len(candidates))

        logger.info(
            "[pipeline] _retrieve done: final=%d fallback_mode=%s warnings=%s",
            len(candidates), fallback_mode, warnings or "none",
        )
        return candidates, fallback_mode, warnings

    async def _keyword_split_retrieve(
        self,
        query: ArtworkQuery,
        museum_candidates: list[ArtworkCandidate],
        limit: int,
    ) -> list[ArtworkCandidate]:
        top_keywords = query.keywords[:3]
        if not top_keywords:
            return aggregate_candidates([museum_candidates, []], limit=limit)

        async def search_kw(kw: str) -> list[ArtworkCandidate]:
            kw_query = ArtworkQuery(
                raw_text=kw,
                artist=query.artist,
                keywords=[kw],
                confidence=0.3,
            )
            raw = await _safe(
                self.vector_search.search(kw_query, limit=max(limit // 2, 2), score_threshold=0.15)
            )
            return raw if not isinstance(raw, Exception) else []

        per_keyword = await asyncio.gather(*[search_kw(kw) for kw in top_keywords])
        all_vector = [c for group in per_keyword for c in group]
        return aggregate_candidates([museum_candidates, all_vector], limit=limit)


# ---------------------------------------------------------------------------
# Clarification hint generation (Layer 1)
# ---------------------------------------------------------------------------

_DIMENSION_RULES: list[tuple[list[str], str]] = [
    (["which", "version", "variation", "series"],
     "Do you know which version or series? E.g. a specific year, theme, or museum collection."),
    (["artist uncertain", "artist unknown", " or "],
     "Are you sure about the artist? Any additional clue helps."),
    (["composition unknown", "subject unknown"],
     "What are the main figures or scenes in the painting?"),
    (["period", "century", "decade", "era"],
     "Roughly what era or period? E.g. Renaissance, late 19th century..."),
    (["style", "movement", "genre"],
     "What art style or movement? E.g. Impressionism, Realism, Abstract..."),
]

_CLARIFICATION_CONFIDENCE_MAX = 0.65   # was 0.5 — too narrow; show hint up to medium confidence
_CLARIFICATION_CANDIDATES_MAX = 5     # was 3 — 5+ good results means we don't need to ask


def _dimension_to_question(dimension: str) -> str:
    lower = dimension.lower()
    for keywords, question in _DIMENSION_RULES:
        if any(kw in lower for kw in keywords):
            return question
    return "Could you add more details? E.g. subject matter, era, artist, or style."


def _make_clarification(
    query: ArtworkQuery,
    candidates: list[ArtworkCandidate],
) -> ClarificationHint | None:
    if (
        query.confidence >= _CLARIFICATION_CONFIDENCE_MAX
        or len(candidates) >= _CLARIFICATION_CANDIDATES_MAX
        or not query.ambiguity_dimensions
    ):
        return None
    top_dimension = query.ambiguity_dimensions[0]
    return ClarificationHint(
        question=_dimension_to_question(top_dimension),
        dimension=top_dimension,
    )


def _restrict_query(query: ArtworkQuery) -> ArtworkQuery:
    ambiguity_text = " ".join(query.ambiguity_dimensions).lower()
    drop_title = bool(query.ambiguity_dimensions) and (
        "which" in ambiguity_text or "title" in ambiguity_text
    )
    drop_artist = "artist uncertain" in ambiguity_text or "artist unknown" in ambiguity_text
    return ArtworkQuery(
        raw_text=query.raw_text,
        title=None if drop_title else query.title,
        artist=None if drop_artist else query.artist,
        style=query.style,
        medium=query.medium,
        keywords=query.keywords,
        confidence=query.confidence,
    )


async def _safe(coro):  # type: ignore[no-untyped-def]
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001
        return exc


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)
