from __future__ import annotations

import asyncio
from typing import Any

from app.models import ArtworkQuery
from app.providers import AicProvider, CmaProvider, MetProvider, RijksProvider, WikiProvider


class FakeJsonClient:
    def __init__(self, responses: dict[str, dict[str, Any] | list[dict[str, Any]]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    async def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append((url, params or {}, headers or {}))
        for marker, response in self.responses.items():
            if marker in url:
                if isinstance(response, list):
                    if not response:
                        raise AssertionError(f"No remaining fake response for {url}")
                    return response.pop(0)
                return response
        raise AssertionError(f"No fake response for {url}")


def test_cma_provider_maps_search_results() -> None:
    http = FakeJsonClient(
        {
            "/artworks/": {
                "data": [
                    {
                        "id": 1,
                        "accession_number": "1953.424",
                        "title": "Water Lilies",
                        "creators": [{"description": "Claude Monet"}],
                        "creation_date": "c. 1915-1926",
                        "type": "Painting",
                        "department": "Modern European Painting and Sculpture",
                        "share_license_status": "CC0",
                        "images": {
                            "web": {"url": "https://cdn.example/web.jpg"},
                            "print": {"url": "https://cdn.example/print.jpg"},
                            "full": {"url": "https://cdn.example/full.tif"},
                        },
                        "url": "https://www.clevelandart.org/art/1953.424",
                    }
                ]
            }
        }
    )
    query = ArtworkQuery(raw_text="water lilies", title="Water Lilies", artist="Monet")

    result = asyncio.run(CmaProvider(http=http).search(query, limit=5))

    assert result[0].provider_id == "cma"
    assert result[0].title == "Water Lilies"
    assert result[0].artist == "Claude Monet"
    assert result[0].free_image_available is True
    assert result[0].image_refs["original_format"] == "tiff"


def test_aic_provider_uses_image_id_and_marks_proxy_capability() -> None:
    http = FakeJsonClient(
        {
            "/artworks/search": {
                "config": {"iiif_url": "https://www.artic.edu/iiif/2"},
                "data": [
                    {
                        "id": 27992,
                        "title": "Paris Street; Rainy Day",
                        "artist_display": "Gustave Caillebotte",
                        "date_display": "1877",
                        "medium_display": "Oil on canvas",
                        "image_id": "abc-123",
                        "is_public_domain": True,
                        "api_link": "https://api.artic.edu/api/v1/artworks/27992",
                        "web_url": "https://www.artic.edu/artworks/27992",
                    }
                ],
            }
        }
    )

    result = asyncio.run(AicProvider(http=http).search(ArtworkQuery(raw_text="rainy day"), limit=1))

    assert result[0].provider_id == "aic"
    assert result[0].provider_image_id == "abc-123"
    assert result[0].iiif_base_url == "https://www.artic.edu/iiif/2/abc-123"
    assert result[0].capabilities["requires_proxy"] is True


def test_met_provider_searches_ids_then_fetches_details() -> None:
    http = FakeJsonClient(
        {
            "/search": {"objectIDs": [45734]},
            "/objects/45734": {
                "objectID": 45734,
                "title": "Wheat Field with Cypresses",
                "artistDisplayName": "Vincent van Gogh",
                "objectDate": "1889",
                "medium": "Oil on canvas",
                "isPublicDomain": True,
                "primaryImage": "https://images.metmuseum.org/full.jpg",
                "primaryImageSmall": "https://images.metmuseum.org/small.jpg",
                "objectWikidata_URL": "https://www.wikidata.org/wiki/Q1991166",
                "objectURL": "https://www.metmuseum.org/art/collection/search/45734",
            },
        }
    )

    result = asyncio.run(MetProvider(http=http).search(ArtworkQuery(raw_text="cypresses"), limit=1))

    assert result[0].provider_id == "met"
    assert result[0].wikidata_id == "Q1991166"
    assert result[0].image_url == "https://images.metmuseum.org/full.jpg"
    assert len(http.calls) == 2


def test_rijks_provider_resolves_lod_ids_to_micrio_candidates() -> None:
    lod_url = "https://id.rijksmuseum.nl/200100988"
    http = FakeJsonClient(
        {
            "search/collection": {"orderedItems": [lod_url]},
            "200100988": {
                "identified_by": [{"content": "The Night Watch"}],
                "image": {"access_point": "https://iiif.micr.io/RFwqO"},
            },
        }
    )

    result = asyncio.run(RijksProvider(http=http).search(ArtworkQuery(raw_text="Night Watch"), limit=1))

    assert result[0].provider_id == "rijks"
    assert result[0].provider_image_id == "RFwqO"
    assert result[0].iiif_base_url == "https://iiif.micr.io/RFwqO"
    assert result[0].capabilities["supports_region"] is True


def test_wiki_provider_searches_commons_and_resolves_imageinfo() -> None:
    http = FakeJsonClient(
        {
            "commons.wikimedia.org": [
                {
                    "query": {
                        "search": [
                            {
                                "title": "File:Great Wave off Kanagawa.jpg",
                                "pageid": 123,
                                "snippet": "wave print",
                            }
                        ]
                    }
                },
                {
                    "query": {
                        "pages": [
                            {
                                "pageid": 123,
                                "title": "File:Great Wave off Kanagawa.jpg",
                                "imageinfo": [
                                    {
                                        "url": "https://upload.wikimedia.org/original.jpg",
                                        "thumburl": "https://upload.wikimedia.org/thumb-2000.jpg",
                                        "width": 4000,
                                        "height": 2600,
                                        "thumbwidth": 2000,
                                        "thumbheight": 1300,
                                        "mime": "image/jpeg",
                                    }
                                ],
                            }
                        ]
                    }
                },
            ],
            "sparql": {"results": {"bindings": []}},
        }
    )

    result = asyncio.run(WikiProvider(http=http).search(ArtworkQuery(raw_text="great wave"), limit=1))

    assert result[0].provider_id == "commons"
    assert result[0].source_api == "commons"
    assert result[0].commons_filename == "Great Wave off Kanagawa.jpg"
    assert result[0].image_url == "https://upload.wikimedia.org/thumb-2000.jpg"
    assert result[0].image_refs["width"] == 4000
    assert result[0].license_status == "commons"
    assert result[0].is_public_domain is None


def test_wiki_provider_maps_sparql_bindings_to_candidates() -> None:
    http = FakeJsonClient(
        {
            "sparql": {
                "results": {
                    "bindings": [
                        {
                            "item": {"value": "https://www.wikidata.org/entity/Q45585"},
                            "itemLabel": {"value": "The Great Wave off Kanagawa"},
                            "creatorLabel": {"value": "Katsushika Hokusai"},
                            "image": {
                                "value": "http://commons.wikimedia.org/wiki/Special:FilePath/Great_Wave_off_Kanagawa.jpg"
                            },
                        }
                    ]
                }
            },
            "commons.wikimedia.org": {
                "query": {
                    "pages": [
                        {
                            "pageid": 456,
                            "title": "File:Great Wave off Kanagawa.jpg",
                            "imageinfo": [
                                {
                                    "url": "https://upload.wikimedia.org/original.jpg",
                                    "thumburl": "https://upload.wikimedia.org/thumb-2000.jpg",
                                    "width": 4000,
                                    "height": 2600,
                                    "mime": "image/jpeg",
                                }
                            ],
                        }
                    ]
                }
            },
        }
    )

    result = asyncio.run(WikiProvider(http=http).search_wikidata(ArtworkQuery(raw_text="great wave"), limit=1))

    assert result[0].provider_id == "wikidata"
    assert result[0].wikidata_id == "Q45585"
    assert result[0].commons_filename == "Great Wave off Kanagawa.jpg"
    assert result[0].image_url == "https://upload.wikimedia.org/thumb-2000.jpg"
    assert result[0].free_image_available is True
    assert result[0].is_public_domain is None
