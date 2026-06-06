from __future__ import annotations

import re

from app.models import ArtworkCandidate


def aggregate_candidates(
    ranked_lists: list[list[ArtworkCandidate]],
    limit: int = 8,
    rrf_k: int = 60,
) -> list[ArtworkCandidate]:
    by_key: dict[str, ArtworkCandidate] = {}

    for candidates in ranked_lists:
        for rank, candidate in enumerate(candidates, start=1):
            key = dedupe_key(candidate)
            rrf_score = 1.0 / (rrf_k + rank)
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = candidate.model_copy(
                    update={
                        "score": rrf_score,
                        "matched_sources": sorted(set(candidate.matched_sources or [candidate.source_api])),
                    },
                    deep=True,
                )
                continue

            by_key[key] = merge_candidates(existing, candidate, rrf_score)

    ordered = sorted(
        by_key.values(),
        key=lambda item: item.score + _quality_score(item),
        reverse=True,
    )
    return ordered[:limit]


def _quality_score(c: ArtworkCandidate) -> float:
    """Small tie-breaking bonus for candidates with richer, more usable data.

    Values are intentionally small so they only matter when RRF scores are close.
    """
    score = 0.0
    if c.artist:
        score += 0.003  # card can show artist name
    if c.year:
        score += 0.001  # card can show date
    if c.thumbnail_url:
        score += 0.003  # card has an image to display
    if c.free_image_available:
        score += 0.002  # high-res image accessible
    if len(c.matched_sources) > 1:
        score += 0.004  # found by multiple retrievers
    return score


def merge_candidates(
    existing: ArtworkCandidate,
    incoming: ArtworkCandidate,
    additional_score: float,
) -> ArtworkCandidate:
    matched_sources = sorted(
        set(existing.matched_sources)
        | set(incoming.matched_sources)
        | {existing.source_api, incoming.source_api}
    )
    replacement = existing
    if (not existing.thumbnail_url and incoming.thumbnail_url) or (
        not existing.image_url and incoming.image_url
    ):
        replacement = incoming

    metadata = dict(existing.metadata)
    metadata.setdefault("merged_from", [])
    metadata["merged_from"] = sorted(
        set(metadata["merged_from"])
        | {existing.metadata.get("retrieval_path", existing.source_api)}
        | {incoming.metadata.get("retrieval_path", incoming.source_api)}
    )

    return replacement.model_copy(
        update={
            "score": existing.score + additional_score,
            "matched_sources": matched_sources,
            "metadata": metadata,
        },
        deep=True,
    )


def dedupe_key(candidate: ArtworkCandidate) -> str:
    # Shared wikidata_id is the most reliable dedup signal:
    # e.g. a Wikidata entry and its Commons scan of the same painting both carry Q45585.
    if candidate.wikidata_id:
        return f"wd:{candidate.wikidata_id}"

    # Commons filename is stable and unique per file
    if candidate.commons_filename:
        return f"commons:{candidate.commons_filename.casefold()}"

    # Fallback: normalised title + artist + decade
    title  = _compact(candidate.title)
    artist = _compact(candidate.artist or "")
    year   = _year_bucket(candidate.year or "")
    if title or artist:
        return f"{title}:{artist}:{year}"
    return f"{candidate.source_api}:{candidate.id}"


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _year_bucket(value: str) -> str:
    match = re.search(r"\d{3,4}", value)
    return match.group(0) if match else ""
