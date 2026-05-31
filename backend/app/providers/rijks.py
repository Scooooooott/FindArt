from __future__ import annotations

import asyncio
import re
from typing import Any

from app.models import ArtworkCandidate, ArtworkQuery
from app.providers.base import best_query_text, compact_whitespace
from app.services.cache import TTLCache
from app.services.http_client import JsonHttpClient, UrllibJsonHttpClient


class RijksProvider:
    name = "rijks"
    search_url = "https://data.rijksmuseum.nl/search/collection"

    def __init__(
        self,
        http: JsonHttpClient | None = None,
        detail_cache: TTLCache[dict[str, Any]] | None = None,
    ) -> None:
        self.http = http or UrllibJsonHttpClient()
        self.detail_cache = detail_cache or TTLCache(ttl_seconds=1800)

    async def search(self, query: ArtworkQuery, limit: int) -> list[ArtworkCandidate]:
        params: dict[str, Any] = {"imageAvailable": "true"}
        if query.title:
            params["title"] = query.title
        elif query.artist:
            params["creator"] = query.artist
        else:
            params["description"] = best_query_text(query)

        payload = await self.http.get_json(self.search_url, params=params)
        ids = _ordered_item_ids(payload)
        details = await asyncio.gather(
            *(self._fetch_detail(lod_id) for lod_id in ids[:limit]),
            return_exceptions=True,
        )

        candidates = []
        for lod_id, detail in zip(ids[:limit], details, strict=False):
            if isinstance(detail, Exception) or not isinstance(detail, dict):
                candidates.append(self._minimal_candidate(lod_id))
                continue
            candidates.append(self._to_candidate(lod_id, detail))
        return candidates

    async def _fetch_detail(self, lod_id: str) -> dict[str, Any]:
        cache_key = f"rijks:detail:{lod_id}"
        cached = self.detail_cache.get(cache_key)
        if cached is not None:
            return cached
        detail = await self.http.get_json(
            lod_id,
            headers={"Accept": "application/ld+json"},
        )
        self.detail_cache.set(cache_key, detail)
        return detail

    def _to_candidate(self, lod_id: str, detail: dict[str, Any]) -> ArtworkCandidate:
        object_id = lod_id.rstrip("/").split("/")[-1]
        micrio_id = _extract_micrio_id(detail)
        iiif_base = f"https://iiif.micr.io/{micrio_id}" if micrio_id else None
        title = _identified_title(detail) or _first_string_for_keys(detail, {"title", "_label"}) or "Untitled"
        artist = _first_string_for_keys(detail, {"creator", "artist", "maker"})

        return ArtworkCandidate(
            id=object_id,
            source_api=self.name,
            provider_id=self.name,
            provider_object_id=object_id,
            provider_image_id=micrio_id,
            title=compact_whitespace(title) or "Untitled",
            artist=compact_whitespace(artist),
            thumbnail_url=f"{iiif_base}/full/400,/0/default.jpg" if iiif_base else None,
            source_url=lod_id,
            detail_url=lod_id,
            iiif_base_url=iiif_base,
            is_public_domain=None,
            license_status="unknown",
            image_available=bool(micrio_id),
            free_image_available=bool(micrio_id),
            rights_notice=None if micrio_id else "No free high-resolution image available.",
            image_refs={
                "micrio_id": micrio_id,
            },
            capabilities={
                "supports_region": bool(micrio_id),
                "supports_iiif": bool(micrio_id),
            },
            matched_sources=[self.name],
            metadata={"lod_id": lod_id},
        )

    def _minimal_candidate(self, lod_id: str) -> ArtworkCandidate:
        object_id = lod_id.rstrip("/").split("/")[-1]
        return ArtworkCandidate(
            id=object_id,
            source_api=self.name,
            provider_id=self.name,
            provider_object_id=object_id,
            title=f"Rijksmuseum object {object_id}",
            source_url=lod_id,
            detail_url=lod_id,
            license_status="unknown",
            image_available=None,
            free_image_available=None,
            matched_sources=[self.name],
            metadata={"lod_id": lod_id, "detail_unavailable": True},
        )


def _ordered_item_ids(payload: dict[str, Any]) -> list[str]:
    ordered_items = payload.get("orderedItems")
    if not isinstance(ordered_items, list):
        return []
    ids = []
    for item in ordered_items:
        if isinstance(item, str):
            ids.append(item)
        elif isinstance(item, dict):
            value = item.get("id") or item.get("@id")
            if value:
                ids.append(str(value))
    return ids


def _extract_micrio_id(value: Any) -> str | None:
    for text in _walk_strings(value):
        match = re.search(r"https://iiif\.micr\.io/([A-Za-z0-9_-]+)", text)
        if match:
            return match.group(1)
    return None


def _identified_title(value: Any) -> str | None:
    if isinstance(value, dict):
        identified_by = value.get("identified_by") or value.get("identifiedBy")
        if isinstance(identified_by, list):
            for item in identified_by:
                if isinstance(item, dict) and item.get("content"):
                    return str(item["content"])
        for child in value.values():
            result = _identified_title(child)
            if result:
                return result
    elif isinstance(value, list):
        for child in value:
            result = _identified_title(child)
            if result:
                return result
    return None


def _first_string_for_keys(value: Any, keys: set[str]) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in keys and isinstance(child, str):
                return child
            result = _first_string_for_keys(child, keys)
            if result:
                return result
    elif isinstance(value, list):
        for child in value:
            result = _first_string_for_keys(child, keys)
            if result:
                return result
    return None


def _walk_strings(value: Any) -> list[str]:
    strings: list[str] = []
    if isinstance(value, str):
        strings.append(value)
    elif isinstance(value, dict):
        for child in value.values():
            strings.extend(_walk_strings(child))
    elif isinstance(value, list):
        for child in value:
            strings.extend(_walk_strings(child))
    return strings

