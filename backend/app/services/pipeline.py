from __future__ import annotations

import asyncio
import time
import uuid

from app.models import SearchDiagnostics, SearchResponse
from app.services.aggregation import aggregate_candidates
from app.services.intent import DefaultIntentParser
from app.services.museum import MuseumSearchService
from app.services.vector_search import DefaultVectorSearchService


class SearchPipeline:
    def __init__(
        self,
        intent_parser: DefaultIntentParser | None = None,
        museum_search: MuseumSearchService | None = None,
        vector_search: DefaultVectorSearchService | None = None,
    ) -> None:
        self.intent_parser = intent_parser or DefaultIntentParser()
        self.museum_search = museum_search or MuseumSearchService()
        self.vector_search = vector_search or DefaultVectorSearchService()

    async def search(self, text: str, limit: int = 8) -> SearchResponse:
        request_id = str(uuid.uuid4())
        timings: dict[str, float] = {}
        warnings: list[str] = []

        started = time.perf_counter()
        query = await self.intent_parser.parse(text)
        timings["intent_ms"] = _elapsed_ms(started)

        search_started = time.perf_counter()
        museum_result, vector_result = await asyncio.gather(
            self.museum_search.search(query, limit=limit),
            self.vector_search.search(query, limit=limit),
            return_exceptions=True,
        )
        timings["retrieval_ms"] = _elapsed_ms(search_started)

        museum_candidates = []
        vector_candidates = []
        if isinstance(museum_result, Exception):
            warnings.append(f"museum_search_failed:{museum_result}")
        else:
            museum_candidates = museum_result
            warnings.extend(self.museum_search.last_warnings)

        if isinstance(vector_result, Exception):
            warnings.append(f"vector_search_failed:{vector_result}")
        else:
            vector_candidates = vector_result

        aggregate_started = time.perf_counter()
        candidates = aggregate_candidates(
            [museum_candidates, vector_candidates],
            limit=limit,
        )
        timings["aggregation_ms"] = _elapsed_ms(aggregate_started)
        timings["total_ms"] = _elapsed_ms(started)

        diagnostics = SearchDiagnostics(
            request_id=request_id,
            timings_ms=timings,
            providers=[
                *self.museum_search.provider_names,
                self.vector_search.name,
            ],
            warnings=warnings,
        )
        return SearchResponse(
            request_id=request_id,
            query=query,
            candidates=candidates,
            diagnostics=diagnostics,
        )


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)
