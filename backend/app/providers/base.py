from __future__ import annotations

import re
from typing import Protocol

from app.models import ArtworkCandidate, ArtworkQuery


class ArtworkSearchProvider(Protocol):
    name: str

    async def search(self, query: ArtworkQuery, limit: int) -> list[ArtworkCandidate]:
        ...


def best_query_text(query: ArtworkQuery) -> str:
    if query.title:
        return query.title
    if query.keywords:
        return " ".join(query.keywords)
    return query.raw_text


def extract_wikidata_id(url: str | None) -> str | None:
    if not url:
        return None
    match = re.search(r"(Q\d+)", url)
    return match.group(1) if match else None


def first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if value:
            return value
    return None


def compact_whitespace(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"\s+", " ", value).strip()

