from __future__ import annotations

import re

from app.models import ArtworkQuery


_ALIAS_RULES = [
    {
        "terms": ["pearl earring", "\u73cd\u73e0\u8033\u73af", "\u6234\u73cd\u73e0\u8033\u73af"],
        "title": "Girl with a Pearl Earring",
        "artist": "Johannes Vermeer",
        "keywords": ["girl", "pearl", "earring", "portrait", "vermeer"],
    },
    {
        "terms": ["mona lisa", "la gioconda", "\u8499\u5a1c\u4e3d\u838e"],
        "title": "Mona Lisa",
        "artist": "Leonardo da Vinci",
        "keywords": ["portrait", "woman", "smile", "leonardo"],
    },
    {
        "terms": ["starry night", "\u661f\u6708\u591c", "\u661f\u7a7a"],
        "title": "The Starry Night",
        "artist": "Vincent van Gogh",
        "keywords": ["night", "stars", "village", "cypress", "van gogh"],
    },
    {
        "terms": ["sunflowers", "\u5411\u65e5\u8475"],
        "title": "Sunflowers",
        "artist": "Vincent van Gogh",
        "keywords": ["flowers", "sunflowers", "yellow", "van gogh"],
    },
    {
        "terms": ["great wave", "kanagawa", "\u795e\u5948\u5ddd", "\u51b2\u6d6a"],
        "title": "The Great Wave off Kanagawa",
        "artist": "Katsushika Hokusai",
        "keywords": ["wave", "mount fuji", "sea", "woodblock", "hokusai"],
    },
    {
        "terms": ["the scream", "\u5450\u558a"],
        "title": "The Scream",
        "artist": "Edvard Munch",
        "keywords": ["scream", "bridge", "anxiety", "expressionism", "munch"],
    },
]


class DefaultIntentParser:
    """Deterministic placeholder for the future LLM intent parser."""

    async def parse(self, text: str) -> ArtworkQuery:
        normalized = text.casefold()
        for rule in _ALIAS_RULES:
            if any(term.casefold() in normalized for term in rule["terms"]):
                return ArtworkQuery(
                    raw_text=text,
                    title=rule["title"],
                    artist=rule["artist"],
                    keywords=rule["keywords"],
                    confidence=0.86,
                )

        keywords = _extract_keywords(text)
        return ArtworkQuery(
            raw_text=text,
            keywords=keywords or [text.strip()],
            confidence=0.35,
        )


def _extract_keywords(text: str) -> list[str]:
    latin_tokens = re.findall(r"[A-Za-z][A-Za-z0-9'-]{1,}", text.casefold())
    seen: set[str] = set()
    keywords: list[str] = []
    for token in latin_tokens:
        if token not in seen:
            keywords.append(token)
            seen.add(token)
    return keywords[:8]

