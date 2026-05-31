import asyncio

from app.models import ResolveImageRequest
from app.services.image_resolver import ImageResolver
from app.services.museum import DefaultMuseumAdapter, MuseumSearchService
from app.services.pipeline import SearchPipeline


def _offline_pipeline() -> SearchPipeline:
    return SearchPipeline(
        museum_search=MuseumSearchService(adapters=[DefaultMuseumAdapter()])
    )


def test_search_uses_default_catalog_for_known_artwork() -> None:
    response = asyncio.run(
        _offline_pipeline().search(text="\u73cd\u73e0\u8033\u73af", limit=5)
    )

    assert response.query.title == "Girl with a Pearl Earring"
    assert response.candidates
    assert response.candidates[0].title == "Girl with a Pearl Earring"
    assert "default_catalog" in response.diagnostics.providers
    assert "default_vector" in response.diagnostics.providers


def test_resolve_image_from_candidate() -> None:
    search_response = asyncio.run(
        _offline_pipeline().search(text="starry night", limit=3)
    )
    candidate = search_response.candidates[0]

    response = asyncio.run(
        ImageResolver().resolve(candidate=ResolveImageRequest(candidate=candidate).candidate)
    )

    assert response.id == candidate.id
    assert response.medium_url.endswith("/full/800,/0/default.jpg")
    assert response.full_url.endswith("/full/1600,/0/default.jpg")


def test_resolve_image_by_source_and_id() -> None:
    response = asyncio.run(
        ImageResolver().resolve(
            source_api="moma_default",
            artwork_id="default-moma-starry-night",
        )
    )

    assert response.source_api == "moma_default"
