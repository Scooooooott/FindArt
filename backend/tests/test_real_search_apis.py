from __future__ import annotations

import asyncio
import os

import pytest
from app.models import ArtworkCandidate, ArtworkQuery
from app.providers import AicProvider, CmaProvider, MetProvider, RijksProvider, WikiProvider
from app.services.museum import build_museum_search_service

pytestmark = pytest.mark.real_api

FINDART_RUN_REAL_API_TESTS=1

def _run_real_api_tests_enabled() -> bool:
    return os.getenv("FINDART_RUN_REAL_API_TESTS") == "1"


def _skip_unless_enabled() -> None:
    if not _run_real_api_tests_enabled():
        pytest.skip("Set FINDART_RUN_REAL_API_TESTS=1 to call live external APIs.")


def _assert_candidate_shape(candidate: ArtworkCandidate, provider_id: str) -> None:
    assert candidate.provider_id == provider_id
    assert candidate.source_api == provider_id
    assert candidate.provider_object_id
    assert candidate.title
    assert candidate.image_available is not False
    assert candidate.matched_sources


def test_real_cma_search_water_lilies() -> None:
    _skip_unless_enabled()
    query = ArtworkQuery(raw_text="water lilies monet", title="Water Lilies", artist="Monet")

    results = asyncio.run(CmaProvider().search(query, limit=5))

    assert results
    top = results[0]
    _assert_candidate_shape(top, "cma")
    assert "water" in top.title.casefold() or "lil" in top.title.casefold()
    assert top.thumbnail_url or top.image_refs.get("web")
    assert top.license_status is not None


def test_real_aic_search_paris_street_rainy_day() -> None:
    _skip_unless_enabled()
    query = ArtworkQuery(raw_text="Paris Street Rainy Day", title="Paris Street; Rainy Day")

    results = asyncio.run(AicProvider().search(query, limit=5))

    assert results
    top = results[0]
    _assert_candidate_shape(top, "aic")
    assert top.provider_image_id
    assert top.iiif_base_url and top.provider_image_id in top.iiif_base_url
    assert top.capabilities.get("supports_iiif") is True
    assert top.capabilities.get("requires_proxy") is True


def test_real_met_search_wheat_field_with_cypresses() -> None:
    _skip_unless_enabled()
    query = ArtworkQuery(
        raw_text="Wheat Field with Cypresses van Gogh",
        title="Wheat Field with Cypresses",
        artist="Vincent van Gogh",
    )

    results = asyncio.run(MetProvider().search(query, limit=3))

    assert results
    top = results[0]
    _assert_candidate_shape(top, "met")
    assert top.detail_url
    assert top.image_available is True
    assert top.image_url or top.thumbnail_url


def test_real_rijks_search_night_watch() -> None:
    _skip_unless_enabled()
    query = ArtworkQuery(raw_text="Night Watch Rembrandt", title="Night Watch", artist="Rembrandt van Rijn")

    results = asyncio.run(RijksProvider().search(query, limit=3))

    assert results
    top = results[0]
    _assert_candidate_shape(top, "rijks")
    assert top.detail_url and top.detail_url.startswith("https://id.rijksmuseum.nl/")
    assert top.provider_image_id
    assert top.iiif_base_url and top.iiif_base_url.startswith("https://iiif.micr.io/")
    assert top.capabilities.get("supports_region") is True


def test_real_wiki_search_great_wave() -> None:
    _skip_unless_enabled()
    query = ArtworkQuery(raw_text="The Great Wave off Kanagawa", title="The Great Wave off Kanagawa")

    results = asyncio.run(WikiProvider().search(query, limit=5))

    assert results
    top = results[0]
    assert top.provider_id in {"commons", "wikidata"}
    assert top.commons_filename
    assert top.image_refs.get("commons_original") or top.image_refs.get("commons_medium")


def test_real_combined_external_search_has_candidates_and_warnings_do_not_fail() -> None:
    _skip_unless_enabled()
    service = build_museum_search_service(include_default=False, include_external=True)
    query = ArtworkQuery(raw_text="The Great Wave off Kanagawa", title="The Great Wave off Kanagawa")

    results = asyncio.run(service.search(query, limit=3))

    assert results
    assert any(candidate.provider_id in {"wikidata", "met", "cma", "aic", "rijks"} for candidate in results)
    assert isinstance(service.last_warnings, list)
