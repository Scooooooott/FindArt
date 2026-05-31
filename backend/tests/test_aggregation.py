from app.models import ArtworkCandidate
from app.services.aggregation import aggregate_candidates


def test_aggregate_dedupes_same_artwork_and_combines_sources() -> None:
    api_candidate = ArtworkCandidate(
        id="a",
        source_api="api",
        title="Girl with a Pearl Earring",
        artist="Johannes Vermeer",
        year="1665",
        thumbnail_url="https://example.com/a.jpg",
        matched_sources=["api"],
    )
    vector_candidate = ArtworkCandidate(
        id="b",
        source_api="vector",
        title="Girl, with a Pearl Earring",
        artist="Johannes Vermeer",
        year="1665",
        matched_sources=["vector"],
    )

    result = aggregate_candidates([[api_candidate], [vector_candidate]], limit=5)

    assert len(result) == 1
    assert result[0].thumbnail_url == "https://example.com/a.jpg"
    assert set(result[0].matched_sources) == {"api", "vector"}
    assert result[0].score > 0


def test_aggregate_keeps_distinct_titles() -> None:
    first = ArtworkCandidate(id="1", source_api="api", title="Mona Lisa", artist="Leonardo")
    second = ArtworkCandidate(id="2", source_api="api", title="The Scream", artist="Munch")

    result = aggregate_candidates([[first, second]], limit=5)

    assert [item.title for item in result] == ["Mona Lisa", "The Scream"]

