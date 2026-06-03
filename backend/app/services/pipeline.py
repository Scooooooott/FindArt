from __future__ import annotations

import asyncio
import time
import uuid

from app.models import ArtworkCandidate, ArtworkQuery, ClarificationHint, SearchDiagnostics, SearchResponse
from app.services.aggregation import aggregate_candidates
from app.services.intent import IntentParser, create_intent_parser
from app.services.museum import MuseumSearchService
from app.services.vector_search import VectorSearchService, create_vector_search_service

# Minimum candidate count before each fallback strategy activates
_THRESHOLD_RELAX = 3    # fewer than this → try relaxed vector threshold
_THRESHOLD_RESTRICT = 2  # fewer than this → try field-restricted query
_THRESHOLD_SPLIT = 1    # fewer than this → try keyword split


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
        warnings: list[str] = []
        fallback_mode: str | None = None

        # ── M1: Intent parsing ──────────────────────────────────────────────
        t0 = time.perf_counter()
        query = await self.intent_parser.parse(text)
        timings["intent_ms"] = _elapsed_ms(t0)

        # ── M2: Museum API search (run once; not repeated in fallback) ──────
        t1 = time.perf_counter()
        museum_raw = await _safe(self.museum_search.search(query, limit=limit))
        if isinstance(museum_raw, Exception):
            warnings.append(f"museum_search_failed:{museum_raw}")
            museum_candidates: list[ArtworkCandidate] = []
        else:
            museum_candidates = museum_raw
            warnings.extend(self.museum_search.last_warnings)

        # ── M3 + M4: Vector search with progressive fallback ────────────────

        # Strategy 1 — normal threshold
        candidates = await self._retrieve(query, museum_candidates, limit, threshold=0.3)

        # Strategy 2 — relax vector threshold
        if len(candidates) < _THRESHOLD_RELAX:
            relaxed = await self._retrieve(query, museum_candidates, limit, threshold=0.15)
            if len(relaxed) > len(candidates):
                candidates = relaxed
                fallback_mode = "relaxed_threshold"

        # Strategy 3 — drop uncertain fields from query
        if len(candidates) < _THRESHOLD_RESTRICT:
            restricted_q = _restrict_query(query)
            restricted = await self._retrieve(restricted_q, museum_candidates, limit, threshold=0.2)
            if len(restricted) > len(candidates):
                candidates = restricted
                fallback_mode = "field_restricted"

        # Strategy 4 — keyword split and union
        if len(candidates) < _THRESHOLD_SPLIT:
            split = await self._keyword_split_retrieve(query, museum_candidates, limit)
            if len(split) > len(candidates):
                candidates = split
                fallback_mode = "keyword_split"

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

    async def _retrieve(
        self,
        query: ArtworkQuery,
        museum_candidates: list[ArtworkCandidate],
        limit: int,
        threshold: float,
    ) -> list[ArtworkCandidate]:
        """Combine pre-fetched museum results with a fresh vector search, then aggregate."""
        vector_raw = await _safe(self.vector_search.search(query, limit=limit, score_threshold=threshold))
        vector_candidates = vector_raw if not isinstance(vector_raw, Exception) else []
        return aggregate_candidates([museum_candidates, vector_candidates], limit=limit)

    async def _keyword_split_retrieve(
        self,
        query: ArtworkQuery,
        museum_candidates: list[ArtworkCandidate],
        limit: int,
    ) -> list[ArtworkCandidate]:
        """Search each keyword individually, union the vector results, then aggregate."""
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
            raw = await _safe(self.vector_search.search(kw_query, limit=max(limit // 2, 2), score_threshold=0.15))
            return raw if not isinstance(raw, Exception) else []

        per_keyword = await asyncio.gather(*[search_kw(kw) for kw in top_keywords])
        all_vector = [c for group in per_keyword for c in group]
        return aggregate_candidates([museum_candidates, all_vector], limit=limit)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Clarification hint generation (Layer 1)
# ---------------------------------------------------------------------------

# Each rule: (substrings to match in dimension, Chinese follow-up question)
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

_CLARIFICATION_CONFIDENCE_MAX = 0.5   # only clarify when confidence is low
_CLARIFICATION_CANDIDATES_MAX = 3     # only clarify when few results found


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
    """Drop fields that ambiguity_dimensions flags as uncertain."""
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
    """Await a coroutine, returning the exception instead of raising it."""
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001
        return exc


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)
