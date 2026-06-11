from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Sequence
from typing import Protocol

logger = logging.getLogger(__name__)

from app.data.default_catalog import DEFAULT_CATALOG
from app.models import ArtworkCandidate, ArtworkQuery
from app.providers import AicProvider, CmaProvider, MetProvider, RijksProvider, WikiProvider

# Map of name → provider factory, used by FINDART_PROVIDERS whitelist.
_PROVIDER_REGISTRY: dict[str, type] = {
    "wiki": WikiProvider,
    "met": MetProvider,
    "aic": AicProvider,
    "cma": CmaProvider,
    "rijks": RijksProvider,
}
_ALL_PROVIDERS = list(_PROVIDER_REGISTRY.keys())


class MuseumAdapter(Protocol):
    name: str

    async def search(self, query: ArtworkQuery, limit: int) -> list[ArtworkCandidate]:
        ...


class DefaultMuseumAdapter:
    name = "default_catalog"

    def __init__(self, catalog: Sequence[dict] | None = None) -> None:
        self.catalog = list(catalog or DEFAULT_CATALOG)

    async def search(self, query: ArtworkQuery, limit: int) -> list[ArtworkCandidate]:
        scored = []
        for item in self.catalog:
            score = score_catalog_item(item, query)
            if score > 0:
                scored.append((score, item))

        if not scored:
            scored = [(0.1, item) for item in self.catalog[:limit]]

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            candidate_from_catalog(item, score=score, retrieval_path=self.name)
            for score, item in scored[:limit]
        ]


class MuseumSearchService:
    def __init__(self, adapters: Sequence[MuseumAdapter] | None = None) -> None:
        self.adapters = list(adapters or [DefaultMuseumAdapter()])
        self.last_warnings: list[str] = []

    async def search(self, query: ArtworkQuery, limit: int) -> list[ArtworkCandidate]:
        self.last_warnings = []
        results = await asyncio.gather(
            *(adapter.search(query, limit=limit) for adapter in self.adapters),
            return_exceptions=True,
        )

        candidates: list[ArtworkCandidate] = []
        for adapter, result in zip(self.adapters, results, strict=False):
            if isinstance(result, Exception):
                self.last_warnings.append(f"{adapter.name}_failed:{result}")
                logger.warning(
                    "[museum] Provider '%s' failed: %s",
                    adapter.name, result, exc_info=result,
                )
                continue
            logger.info("[museum] Provider '%s' returned %d candidates", adapter.name, len(result))
            candidates.extend(result)
        return candidates

    @property
    def provider_names(self) -> list[str]:
        return [adapter.name for adapter in self.adapters]


def candidate_from_catalog(
    item: dict,
    score: float = 0.0,
    retrieval_path: str = "default_catalog",
) -> ArtworkCandidate:
    return ArtworkCandidate(
        id=item["id"],
        source_api=item["source_api"],
        provider_id=item.get("provider_id") or item["source_api"],
        provider_object_id=item["id"],
        title=item["title"],
        artist=item.get("artist"),
        year=item.get("year"),
        medium=item.get("medium"),
        thumbnail_url=item.get("thumbnail_url"),
        source_url=item.get("source_url"),
        image_url=item.get("image_url"),
        iiif_base_url=item.get("iiif_base_url"),
        is_public_domain=True,
        license_status="default",
        image_available=bool(item.get("thumbnail_url") or item.get("image_url") or item.get("iiif_base_url")),
        free_image_available=True,
        image_refs={
            "thumbnail": item.get("thumbnail_url"),
            "image": item.get("image_url"),
            "iiif_base": item.get("iiif_base_url"),
        },
        capabilities={
            "supports_region": bool(item.get("iiif_base_url")),
            "supports_iiif": bool(item.get("iiif_base_url")),
        },
        score=score,
        matched_sources=[item["source_api"]],
        metadata={
            "retrieval_path": retrieval_path,
            "period": item.get("period"),
            "style": item.get("style"),
        },
    )


def score_catalog_item(item: dict, query: ArtworkQuery) -> float:
    haystack = " ".join(
        str(value)
        for value in [
            item.get("title"),
            item.get("artist"),
            item.get("period"),
            item.get("style"),
            item.get("medium"),
            " ".join(item.get("keywords", [])),
            " ".join(item.get("aliases", [])),
        ]
        if value
    ).casefold()

    score = 0.0
    weighted_terms = [
        (query.title, 8.0),
        (query.artist, 6.0),
        (query.period, 3.0),
        (query.style, 3.0),
        (query.medium, 2.0),
    ]
    for term, weight in weighted_terms:
        if term and term.casefold() in haystack:
            score += weight

    for keyword in query.keywords:
        normalized = keyword.casefold().strip()
        if normalized and normalized in haystack:
            score += 1.5

    raw_terms = _tokenize(query.raw_text)
    for token in raw_terms:
        if token in haystack:
            score += 0.25

    return score


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]{2,}", text.casefold())


def build_museum_search_service(
    include_default: bool = True,
    include_external: bool = True,
) -> MuseumSearchService:
    adapters: list[MuseumAdapter] = []
    if include_default:
        adapters.append(DefaultMuseumAdapter())
    if include_external:
        raw = os.getenv("FINDART_PROVIDERS", "").strip()
        enabled = [p.strip().lower() for p in raw.split(",") if p.strip()] if raw else _ALL_PROVIDERS
        for name in enabled:
            factory = _PROVIDER_REGISTRY.get(name)
            if factory is None:
                import warnings
                warnings.warn(f"FINDART_PROVIDERS: unknown provider '{name}', skipping.")
                continue
            adapters.append(factory())
    return MuseumSearchService(adapters=adapters)
