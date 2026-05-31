from __future__ import annotations

from typing import Any

from app.models import ArtworkCandidate, ArtworkQuery
from app.providers.base import best_query_text, compact_whitespace
from app.services.http_client import JsonHttpClient, UrllibJsonHttpClient


class CmaProvider:
    name = "cma"
    base_url = "https://openaccess-api.clevelandart.org/api"

    def __init__(self, http: JsonHttpClient | None = None) -> None:
        self.http = http or UrllibJsonHttpClient()

    async def search(self, query: ArtworkQuery, limit: int) -> list[ArtworkCandidate]:
        params: dict[str, Any] = {
            "limit": limit,
            "has_image": "1",
        }
        if query.title:
            params["title"] = query.title
        else:
            params["q"] = best_query_text(query)
        if query.artist:
            params["artists"] = query.artist
        if query.medium:
            params["type"] = query.medium

        payload = await self.http.get_json(f"{self.base_url}/artworks/", params=params)
        items = payload.get("data", [])
        if not isinstance(items, list):
            return []
        return [self._to_candidate(item) for item in items[:limit] if isinstance(item, dict)]

    def _to_candidate(self, item: dict[str, Any]) -> ArtworkCandidate:
        object_id = str(item.get("id") or item.get("accession_number") or "")
        images = item.get("images") if isinstance(item.get("images"), dict) else {}
        web = _image_url(images, "web")
        print_url = _image_url(images, "print")
        full = _image_url(images, "full")
        license_status = item.get("share_license_status")
        is_public_domain = license_status == "CC0"
        creators = item.get("creators") if isinstance(item.get("creators"), list) else []
        artist = _creators_label(creators)

        return ArtworkCandidate(
            id=object_id,
            source_api=self.name,
            provider_id=self.name,
            provider_object_id=object_id,
            title=str(item.get("title") or "Untitled"),
            artist=artist,
            year=compact_whitespace(item.get("creation_date")),
            medium=compact_whitespace(item.get("type")),
            thumbnail_url=web,
            source_url=item.get("url"),
            detail_url=f"{self.base_url}/artworks/{object_id}" if object_id else None,
            image_url=print_url or web,
            is_public_domain=is_public_domain,
            license_status=license_status,
            image_available=bool(web or print_url or full),
            free_image_available=is_public_domain and bool(web or print_url or full),
            rights_notice=None if is_public_domain else "No free high-resolution image available.",
            image_refs={
                "web": web,
                "print": print_url,
                "original": full,
                "original_format": "tiff" if full else None,
            },
            capabilities={
                "supports_region": False,
                "supports_iiif": False,
                "has_original_tiff": bool(full),
            },
            matched_sources=[self.name],
            metadata={
                "accession_number": item.get("accession_number"),
                "department": item.get("department"),
                "collection": item.get("collection"),
            },
        )


def _image_url(images: dict[str, Any], key: str) -> str | None:
    value = images.get(key)
    if isinstance(value, dict):
        url = value.get("url")
        return str(url) if url else None
    return None


def _creators_label(creators: list[Any]) -> str | None:
    labels = []
    for creator in creators:
        if not isinstance(creator, dict):
            continue
        label = creator.get("description") or creator.get("name")
        if label:
            labels.append(str(label))
    return "; ".join(labels) if labels else None

