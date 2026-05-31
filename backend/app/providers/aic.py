from __future__ import annotations

from typing import Any

from app.models import ArtworkCandidate, ArtworkQuery
from app.providers.base import best_query_text, compact_whitespace
from app.services.http_client import JsonHttpClient, UrllibJsonHttpClient


class AicProvider:
    name = "aic"
    base_url = "https://api.artic.edu/api/v1"
    default_iiif_url = "https://www.artic.edu/iiif/2"

    def __init__(self, http: JsonHttpClient | None = None) -> None:
        self.http = http or UrllibJsonHttpClient()

    async def search(self, query: ArtworkQuery, limit: int) -> list[ArtworkCandidate]:
        fields = ",".join(
            [
                "id",
                "title",
                "artist_display",
                "date_display",
                "medium_display",
                "image_id",
                "is_public_domain",
                "thumbnail",
                "api_link",
                "web_url",
            ]
        )
        params: dict[str, Any] = {
            "q": best_query_text(query),
            "fields": fields,
            "limit": limit,
        }

        payload = await self.http.get_json(f"{self.base_url}/artworks/search", params=params)
        iiif_url = _config_iiif_url(payload) or self.default_iiif_url
        items = payload.get("data", [])
        if not isinstance(items, list):
            return []
        return [
            self._to_candidate(item, iiif_url=iiif_url)
            for item in items[:limit]
            if isinstance(item, dict)
        ]

    def _to_candidate(self, item: dict[str, Any], iiif_url: str) -> ArtworkCandidate:
        object_id = str(item.get("id") or "")
        image_id = item.get("image_id")
        is_public_domain = item.get("is_public_domain")
        thumbnail_url = _thumbnail_url(item, iiif_url)
        native_iiif_base = f"{iiif_url.rstrip('/')}/{image_id}" if image_id else None

        return ArtworkCandidate(
            id=object_id,
            source_api=self.name,
            provider_id=self.name,
            provider_object_id=object_id,
            provider_image_id=str(image_id) if image_id else None,
            title=str(item.get("title") or "Untitled"),
            artist=compact_whitespace(item.get("artist_display")),
            year=compact_whitespace(item.get("date_display")),
            medium=compact_whitespace(item.get("medium_display")),
            thumbnail_url=thumbnail_url,
            source_url=item.get("web_url"),
            detail_url=item.get("api_link") or f"{self.base_url}/artworks/{object_id}",
            iiif_base_url=native_iiif_base,
            is_public_domain=bool(is_public_domain) if is_public_domain is not None else None,
            license_status="public_domain" if is_public_domain else "restricted",
            image_available=bool(image_id),
            free_image_available=bool(is_public_domain and image_id),
            rights_notice=None if is_public_domain else "No free high-resolution image available.",
            image_refs={
                "image_id": image_id,
                "iiif_url": iiif_url,
                "thumbnail": thumbnail_url,
            },
            capabilities={
                "supports_region": bool(image_id),
                "supports_iiif": bool(image_id),
                "requires_proxy": bool(image_id),
            },
            matched_sources=[self.name],
            metadata={},
        )


def _config_iiif_url(payload: dict[str, Any]) -> str | None:
    config = payload.get("config")
    if isinstance(config, dict):
        value = config.get("iiif_url")
        return str(value) if value else None
    return None


def _thumbnail_url(item: dict[str, Any], iiif_url: str) -> str | None:
    thumbnail = item.get("thumbnail")
    if isinstance(thumbnail, dict) and thumbnail.get("lqip"):
        return str(thumbnail["lqip"])
    image_id = item.get("image_id")
    if image_id:
        return f"{iiif_url.rstrip('/')}/{image_id}/full/400,/0/default.jpg"
    return None

