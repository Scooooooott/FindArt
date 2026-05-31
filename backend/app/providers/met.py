from __future__ import annotations

import asyncio
from typing import Any

from app.models import ArtworkCandidate, ArtworkQuery
from app.providers.base import best_query_text, extract_wikidata_id
from app.services.cache import TTLCache
from app.services.http_client import JsonHttpClient, UrllibJsonHttpClient


class MetProvider:
    name = "met"
    base_url = "https://collectionapi.metmuseum.org/public/collection/v1"

    def __init__(
        self,
        http: JsonHttpClient | None = None,
        detail_cache: TTLCache[dict[str, Any]] | None = None,
    ) -> None:
        self.http = http or UrllibJsonHttpClient()
        self.detail_cache = detail_cache or TTLCache(ttl_seconds=1800)

    async def search(self, query: ArtworkQuery, limit: int) -> list[ArtworkCandidate]:
        params: dict[str, Any] = {
            "q": best_query_text(query),
            "hasImages": "true",
        }
        if query.title:
            params["title"] = "true"
        if query.artist and not query.title:
            params["artistOrCulture"] = "true"

        payload = await self.http.get_json(f"{self.base_url}/search", params=params)
        object_ids = payload.get("objectIDs") or []
        if not isinstance(object_ids, list):
            return []

        details = await asyncio.gather(
            *(self._fetch_detail(str(object_id)) for object_id in object_ids[:limit]),
            return_exceptions=True,
        )
        candidates = []
        for detail in details:
            if isinstance(detail, Exception) or not isinstance(detail, dict):
                continue
            candidates.append(self._to_candidate(detail))
        return candidates

    async def _fetch_detail(self, object_id: str) -> dict[str, Any]:
        cache_key = f"met:detail:{object_id}"
        cached = self.detail_cache.get(cache_key)
        if cached is not None:
            return cached
        detail = await self.http.get_json(f"{self.base_url}/objects/{object_id}")
        self.detail_cache.set(cache_key, detail)
        return detail

    def _to_candidate(self, item: dict[str, Any]) -> ArtworkCandidate:
        object_id = str(item.get("objectID") or "")
        wikidata_url = item.get("objectWikidata_URL")
        primary_image = item.get("primaryImage")
        thumbnail = item.get("primaryImageSmall") or primary_image
        is_public_domain = item.get("isPublicDomain")
        free_image_available = bool(is_public_domain and primary_image)

        return ArtworkCandidate(
            id=object_id,
            source_api=self.name,
            provider_id=self.name,
            provider_object_id=object_id,
            title=str(item.get("title") or "Untitled"),
            artist=item.get("artistDisplayName"),
            year=item.get("objectDate"),
            medium=item.get("medium"),
            thumbnail_url=thumbnail,
            source_url=item.get("objectURL"),
            detail_url=f"{self.base_url}/objects/{object_id}",
            image_url=primary_image,
            wikidata_id=extract_wikidata_id(wikidata_url),
            wikidata_url=wikidata_url,
            is_public_domain=bool(is_public_domain) if is_public_domain is not None else None,
            license_status="public_domain" if is_public_domain else "restricted",
            image_available=bool(primary_image or thumbnail),
            free_image_available=free_image_available,
            rights_notice=None if free_image_available else "No free high-resolution image available.",
            image_refs={
                "primary": primary_image,
                "thumbnail": thumbnail,
                "additional": item.get("additionalImages") or [],
            },
            capabilities={
                "supports_region": False,
                "supports_iiif": False,
            },
            matched_sources=[self.name],
            metadata={
                "department": item.get("department"),
                "classification": item.get("classification"),
                "artist_wikidata_url": item.get("artistWikidata_URL"),
            },
        )

