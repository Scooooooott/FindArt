from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote, unquote, urlparse

from app.models import ArtworkCandidate, ArtworkQuery
from app.providers.base import best_query_text, compact_whitespace
from app.services.http_client import JsonHttpClient, UrllibJsonHttpClient

WIKI_USER_AGENT = os.getenv(
    "FINDART_WIKI_USER_AGENT",
    os.getenv(
        "FINDART_USER_AGENT",
        "MasterpieceTracingApp/0.1 (https://example.invalid/findart; contact@example.invalid)",
    ),
)


class WikiProvider:
    name = "wiki"
    commons_endpoint = "https://commons.wikimedia.org/w/api.php"
    sparql_endpoint = "https://query.wikidata.org/sparql"

    def __init__(self, http: JsonHttpClient | None = None) -> None:
        self.http = http or UrllibJsonHttpClient(
            timeout_seconds=30.0,  # SPARQL + mwapi federation is slow
            user_agent=WIKI_USER_AGENT,
        )

    async def search(self, query: ArtworkQuery, limit: int) -> list[ArtworkCandidate]:
        commons_candidates: list[ArtworkCandidate] = []
        wikidata_candidates: list[ArtworkCandidate] = []
        commons_exc: Exception | None = None
        wikidata_exc: Exception | None = None

        try:
            commons_candidates = await self.search_commons(query, limit=limit)
        except Exception as exc:
            commons_exc = exc

        try:
            wikidata_candidates = await self.search_wikidata(query, limit=limit)
        except Exception as exc:
            wikidata_exc = exc

        if commons_exc is not None and wikidata_exc is not None:
            raise wikidata_exc from commons_exc

        candidates = (
            [*wikidata_candidates, *commons_candidates]
            if query.title and wikidata_candidates
            else [*commons_candidates, *wikidata_candidates]
        )
        return _dedupe_candidates(candidates)[:limit]

    async def search_commons(self, query: ArtworkQuery, limit: int) -> list[ArtworkCandidate]:
        payload = await self.http.get_json(
            self.commons_endpoint,
            params={
                "action": "query",
                "list": "search",
                "srsearch": _commons_search_text(query),
                "srnamespace": 6,
                "srlimit": limit,
                "format": "json",
                "formatversion": 2,
            },
            headers=_wiki_headers(),
        )
        search_results = payload.get("query", {}).get("search", [])
        if not isinstance(search_results, list):
            return []

        titles = [
            str(item.get("title"))
            for item in search_results
            if isinstance(item, dict) and item.get("title")
        ]
        pages = await self.resolve_commons_titles(titles)
        candidates = []
        for item in search_results:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "")
            page = pages.get(_normalize_commons_title(title))
            candidates.append(
                _candidate_from_commons_page(
                    page=page,
                    fallback_title=title,
                    source_api="commons",
                    title=_clean_file_title(_filename_from_commons_title(title)),
                    metadata={
                        "search_snippet": item.get("snippet"),
                        "search_title": title,
                        "source": "commons_search",
                    },
                )
            )
        return [candidate for candidate in candidates if candidate is not None]

    async def search_wikidata(self, query: ArtworkQuery, limit: int) -> list[ArtworkCandidate]:
        sparql = _build_sparql(query, limit=limit)
        payload = await self.http.get_json(
            self.sparql_endpoint,
            params={"query": sparql, "format": "json"},
            headers=_wiki_headers({"Accept": "application/sparql-results+json"}),
        )
        bindings = (
            payload.get("results", {}).get("bindings", [])
            if isinstance(payload.get("results"), dict)
            else []
        )
        if not isinstance(bindings, list):
            return []

        bindings = _dedupe_bindings(bindings)
        titles = []
        for binding in bindings:
            image_url = _binding_value(binding, "image")
            filename = _commons_filename_from_url(image_url)
            if filename:
                titles.append(_commons_title(filename))
        pages = await self.resolve_commons_titles(titles)

        return [
            self._to_wikidata_candidate(binding, pages)
            for binding in bindings[:limit]
            if isinstance(binding, dict)
        ]

    async def resolve_commons_titles(self, titles: list[str]) -> dict[str, dict[str, Any]]:
        normalized_titles = [_normalize_commons_title(title) for title in titles if title]
        normalized_titles = list(dict.fromkeys(normalized_titles))
        if not normalized_titles:
            return {}

        payload = await self.http.get_json(
            self.commons_endpoint,
            params={
                "action": "query",
                "titles": "|".join(normalized_titles),
                "prop": "imageinfo",
                "iiprop": "url|size|mime",
                "iiurlwidth": 2000,
                "format": "json",
                "formatversion": 2,
            },
            headers=_wiki_headers(),
        )
        pages = payload.get("query", {}).get("pages", [])
        if isinstance(pages, dict):
            pages = list(pages.values())
        if not isinstance(pages, list):
            return {}
        return {
            _normalize_commons_title(str(page.get("title"))): page
            for page in pages
            if isinstance(page, dict) and page.get("title")
        }

    def _to_wikidata_candidate(
        self,
        binding: dict[str, Any],
        pages: dict[str, dict[str, Any]],
    ) -> ArtworkCandidate:
        item_url = _binding_value(binding, "item")
        wikidata_id = item_url.rstrip("/").split("/")[-1] if item_url else None
        image_url = _binding_value(binding, "image")
        commons_filename = _commons_filename_from_url(image_url)
        page = pages.get(_commons_title(commons_filename)) if commons_filename else None
        candidate = _candidate_from_commons_page(
            page=page,
            fallback_title=_commons_title(commons_filename) if commons_filename else None,
            source_api="wikidata",
            title=_binding_value(binding, "itemLabel") or _clean_file_title(commons_filename),
            artist=compact_whitespace(_binding_value(binding, "creatorLabel")),
            year=compact_whitespace(_binding_value(binding, "date")),
            wikidata_id=wikidata_id,
            wikidata_url=item_url,
            metadata={
                "collection": _binding_value(binding, "collectionLabel"),
                "inventory": _binding_value(binding, "inventory"),
                "source": "wikidata_sparql",
            },
        )
        if candidate is not None:
            return candidate

        return ArtworkCandidate(
            id=wikidata_id or item_url or "wikidata-unknown",
            source_api="wikidata",
            provider_id="wikidata",
            provider_object_id=wikidata_id,
            title=_binding_value(binding, "itemLabel") or "Untitled",
            artist=compact_whitespace(_binding_value(binding, "creatorLabel")),
            year=compact_whitespace(_binding_value(binding, "date")),
            thumbnail_url=_commons_filepath(commons_filename, width=400) if commons_filename else image_url,
            source_url=item_url,
            detail_url=item_url,
            image_url=_commons_filepath(commons_filename, width=2000) if commons_filename else image_url,
            wikidata_id=wikidata_id,
            wikidata_url=item_url,
            commons_filename=commons_filename,
            is_public_domain=None,
            license_status="commons",
            image_available=bool(image_url),
            free_image_available=bool(image_url),
            image_refs={
                "commons_file": commons_filename,
                "commons_original": image_url,
                "commons_medium": _commons_filepath(commons_filename, width=2000) if commons_filename else image_url,
                "commons_thumbnail": _commons_filepath(commons_filename, width=400) if commons_filename else image_url,
            },
            capabilities={
                "supports_region": False,
                "supports_iiif": False,
            },
            matched_sources=[self.name],
            metadata={
                "collection": _binding_value(binding, "collectionLabel"),
                "inventory": _binding_value(binding, "inventory"),
            },
        )


def _build_sparql(query: ArtworkQuery, limit: int) -> str:
    artist_filter = ""
    if query.artist:
        artist = _sparql_string(query.artist)
        artist_filter = f"""
  ?item wdt:P170 ?creator.
  ?creator rdfs:label ?creatorFilterLabel.
  FILTER(LANG(?creatorFilterLabel) = "en")
  FILTER(CONTAINS(LCASE(STR(?creatorFilterLabel)), "{artist}"))
"""
    else:
        artist_filter = "  OPTIONAL { ?item wdt:P170 ?creator. }\n"

    if query.title:
        title = _sparql_literal(query.title)
        item_selector = f'  ?item rdfs:label "{title}"@en.'
    else:
        mwapi_search = _sparql_literal(best_query_text(query))
        item_selector = f"""
  SERVICE wikibase:mwapi {{
    bd:serviceParam wikibase:endpoint "www.wikidata.org";
                    wikibase:api "EntitySearch";
                    mwapi:search "{mwapi_search}";
                    mwapi:language "en".
    ?item wikibase:apiOutputItem mwapi:item.
  }}
""".rstrip()

    return f"""
SELECT ?item ?itemLabel ?creatorLabel ?image ?collectionLabel ?inventory ?date WHERE {{
{item_selector}
  ?item wdt:P18 ?image.
  OPTIONAL {{ ?item rdfs:label ?itemLabel. FILTER(LANG(?itemLabel) = "en") }}
{artist_filter}
  OPTIONAL {{ ?item wdt:P195 ?collection. }}
  OPTIONAL {{ ?item wdt:P217 ?inventory. }}
  OPTIONAL {{ ?item wdt:P571 ?date. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
LIMIT {limit}
""".strip()


def _sparql_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').casefold()


def _sparql_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _binding_value(binding: dict[str, Any], key: str) -> str | None:
    value = binding.get(key)
    if isinstance(value, dict) and value.get("value"):
        return str(value["value"])
    return None


def _commons_search_text(query: ArtworkQuery) -> str:
    parts = []
    if query.title:
        parts.append(query.title)
    if query.artist:
        parts.append(query.artist)
    if not parts:
        parts.extend(query.keywords or [query.raw_text])
    return " ".join(parts)


def _wiki_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    return {
        "User-Agent": WIKI_USER_AGENT,
        "Api-User-Agent": WIKI_USER_AGENT,
        **(extra or {}),
    }


def _dedupe_bindings(bindings: list[Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        key = _binding_value(binding, "item") or _binding_value(binding, "image")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(binding)
    return deduped


def _dedupe_candidates(candidates: list[ArtworkCandidate]) -> list[ArtworkCandidate]:
    seen: set[str] = set()
    deduped: list[ArtworkCandidate] = []
    for candidate in candidates:
        key = candidate.wikidata_id or candidate.commons_filename or candidate.id
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _candidate_from_commons_page(
    page: dict[str, Any] | None,
    fallback_title: str | None,
    source_api: str,
    title: str | None = None,
    artist: str | None = None,
    year: str | None = None,
    wikidata_id: str | None = None,
    wikidata_url: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ArtworkCandidate | None:
    page = page or {}
    page_title = str(page.get("title") or fallback_title or "")
    commons_filename = _filename_from_commons_title(page_title)
    imageinfo = _first_imageinfo(page)
    original_url = _imageinfo_value(imageinfo, "url")
    medium_url = _imageinfo_value(imageinfo, "thumburl") or _commons_filepath(commons_filename, width=2000)
    thumbnail_url = medium_url or _commons_filepath(commons_filename, width=400)
    if not commons_filename and not original_url and not medium_url:
        return None

    pageid = page.get("pageid")
    provider_id = "commons" if source_api == "commons" else "wikidata"
    source_url = _commons_file_page(commons_filename)
    candidate_id = (
        wikidata_id
        or (f"commons:{pageid}" if pageid is not None else None)
        or f"commons:{commons_filename}"
    )

    image_refs = {
        "commons_file": commons_filename,
        "commons_original": original_url,
        "commons_medium": medium_url,
        "commons_thumbnail": thumbnail_url,
        "width": _imageinfo_value(imageinfo, "width"),
        "height": _imageinfo_value(imageinfo, "height"),
        "thumbwidth": _imageinfo_value(imageinfo, "thumbwidth"),
        "thumbheight": _imageinfo_value(imageinfo, "thumbheight"),
        "mime": _imageinfo_value(imageinfo, "mime"),
    }

    return ArtworkCandidate(
        id=candidate_id,
        source_api=source_api,
        provider_id=provider_id,
        provider_object_id=str(pageid or wikidata_id or commons_filename),
        title=title or _clean_file_title(commons_filename) or "Untitled",
        artist=artist,
        year=year,
        thumbnail_url=thumbnail_url,
        source_url=wikidata_url or source_url,
        detail_url=source_url,
        image_url=medium_url or original_url,
        wikidata_id=wikidata_id,
        wikidata_url=wikidata_url,
        commons_filename=commons_filename,
        is_public_domain=None,
        license_status="commons",
        image_available=bool(original_url or medium_url),
        free_image_available=bool(original_url or medium_url),
        image_refs=image_refs,
        capabilities={
            "supports_region": False,
            "supports_iiif": False,
        },
        matched_sources=[source_api],
        metadata=metadata or {},
    )


def _first_imageinfo(page: dict[str, Any]) -> dict[str, Any] | None:
    imageinfo = page.get("imageinfo")
    if isinstance(imageinfo, list) and imageinfo and isinstance(imageinfo[0], dict):
        return imageinfo[0]
    return None


def _imageinfo_value(imageinfo: dict[str, Any] | None, key: str) -> Any:
    if not imageinfo:
        return None
    return imageinfo.get(key)


def _commons_filename_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    filename = parsed.path.rstrip("/").split("/")[-1]
    if not filename:
        return None
    return unquote(filename).replace("_", " ")


def _filename_from_commons_title(title: str | None) -> str | None:
    if not title:
        return None
    value = title.strip()
    if value.casefold().startswith("file:"):
        value = value.split(":", 1)[1]
    return value.replace("_", " ")


def _normalize_commons_title(title: str) -> str:
    filename = _filename_from_commons_title(title) or title
    return _commons_title(filename)


def _commons_title(filename: str | None) -> str:
    if not filename:
        return ""
    if filename.casefold().startswith("file:"):
        return filename
    return f"File:{filename}"


def _commons_filepath(filename: str | None, width: int | None = None) -> str | None:
    if not filename:
        return None
    base = f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(filename, safe='')}"
    return f"{base}?width={width}" if width else base


def _commons_file_page(filename: str | None) -> str | None:
    if not filename:
        return None
    return f"https://commons.wikimedia.org/wiki/{quote(_commons_title(filename).replace(' ', '_'), safe=':/')}"


def _clean_file_title(filename: str | None) -> str | None:
    if not filename:
        return None
    value = filename.rsplit("/", 1)[-1]
    if "." in value:
        value = value.rsplit(".", 1)[0]
    return value.replace("_", " ").strip() or None


class WikidataProvider(WikiProvider):
    """Backward-compatible name for the Wiki search provider."""
