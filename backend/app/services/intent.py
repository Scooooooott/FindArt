from __future__ import annotations

import logging
import os
import re
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.models import ArtworkQuery
from app.services.cache import TTLCache

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol — lets pipeline accept any parser without importing concrete types
# ---------------------------------------------------------------------------

class IntentParser(Protocol):
    async def parse(self, text: str) -> ArtworkQuery: ...


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert art historian and museum search assistant. Users describe \
artworks they want to find so they can copy them for painting practice. Parse \
their description — however vague, informal, or in any language — into \
structured search parameters.

## YOUR TASK
Use your art-history knowledge to identify the most likely artwork(s). Reason \
from indirect clues: visual features, emotional tone, subject matter, cultural \
context, or nicknames. Even a vague description should yield useful keywords.

## OUTPUT FIELDS  (always in English)

title      — Canonical Western title. Use the most common English name.
             Null only when genuinely impossible to guess.
artist     — Full name (e.g. "Johannes Vermeer", not "Vermeer").
             Null if unknown.
period     — Year or decade (e.g. "1665", "1880s", "early 17th century").
             Null if unknown.
style      — Art movement or style (e.g. "Dutch Golden Age", "Ukiyo-e",
             "Surrealism"). Null if unknown.
medium     — Material + support (e.g. "oil on canvas", "woodblock print").
             Null if unknown.
keywords   — 5–10 English terms for museum-database text search. Include:
               • Title variants and translations
               • Artist name variants (short, full, romanizations)
               • Subject matter (figures, objects, setting)
               • Distinctive visual features
               • Style / period terms relevant to this work
confidence — Float 0.0–1.0: how specifically the description points to ONE work.
               0.90–1.00  Unambiguously a specific famous artwork
               0.70–0.89  Very likely one work; minor version/edition uncertainty
               0.50–0.69  Narrowed to an artist or series; multiple works match
               0.25–0.49  Only style/period/subject known; many works qualify
               0.00–0.24  Extremely vague; almost any artwork could match
ambiguity_dimensions — List the aspects still unclear (empty if fully identified).
               Examples: ["which Van Gogh sunflowers version",
                          "artist uncertain — Monet or Pissarro?"]

## INFERENCE EXAMPLES

"那幅戴珍珠耳环的女孩"
→ title="Girl with a Pearl Earring", artist="Johannes Vermeer",
  period="1665", style="Dutch Golden Age", medium="oil on canvas",
  keywords=["girl with a pearl earring","Vermeer","Johannes Vermeer",
            "pearl earring","portrait","Dutch Golden Age"],
  confidence=0.95, ambiguity_dimensions=[]

"钟表融化的那幅画"
→ title="The Persistence of Memory", artist="Salvador Dalí",
  style="Surrealism",
  keywords=["persistence of memory","melting clocks","Dalí","Salvador Dali",
            "Surrealism","soft watches","dreamscape"],
  confidence=0.93, ambiguity_dimensions=[]

"有荷花的印象派画"
→ title=null, artist="Claude Monet", style="Impressionism",
  keywords=["water lilies","Monet","Claude Monet","pond","lotus",
            "Impressionism","Nymphéas","reflections"],
  confidence=0.55,
  ambiguity_dimensions=["which Water Lilies painting — Monet made 250+ variations"]

"蓝色忧郁的女人"
→ title=null, artist="Pablo Picasso", style="Blue Period",
  keywords=["Picasso","Pablo Picasso","Blue Period","woman","blue",
            "melancholy","sadness","poverty"],
  confidence=0.40,
  ambiguity_dimensions=["which Blue Period work — many candidates",
                        "subject and composition unknown"]

"伦勃朗的自画像"
→ title=null, artist="Rembrandt van Rijn",
  keywords=["Rembrandt","self-portrait","Rembrandt van Rijn","Dutch Baroque",
            "chiaroscuro"],
  confidence=0.45,
  ambiguity_dimensions=["which self-portrait — Rembrandt made ~80 over his lifetime"]

"那幅卡拉瓦乔戏剧性的光影"
→ title=null, artist="Caravaggio", style="Baroque",
  keywords=["Caravaggio","chiaroscuro","Baroque","tenebrism","dramatic lighting",
            "Italian Baroque"],
  confidence=0.30,
  ambiguity_dimensions=["which Caravaggio — most of his works use chiaroscuro"]

## RULES
- Translate everything to English; Chinese / Japanese / other-language inputs are common.
- Prioritise famous, widely-reproduced works — those are most likely what someone wants to copy.
- If you can identify the artist but not the specific work, still fill in artist, style,
  medium, and good keywords; set confidence 0.40–0.60.
- Never invent specific details you are unsure about — use null and lower confidence.
- keywords must be useful for English-language museum API text search.
"""


# ---------------------------------------------------------------------------
# Internal schema for LLM structured output
# ---------------------------------------------------------------------------

class _ParsedIntent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str | None = None
    artist: str | None = None
    period: str | None = None
    style: str | None = None
    medium: str | None = None
    keywords: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.35)
    ambiguity_dimensions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# LLM-backed parser (Gemini)
# ---------------------------------------------------------------------------

class LLMIntentParser:
    """Gemini-backed intent parser; falls back to DefaultIntentParser on error."""

    def __init__(self, api_key: str, model: str) -> None:
        try:
            from google import genai
            from google.genai import types as genai_types
        except ImportError as exc:
            raise RuntimeError(
                "google-genai package is not installed. "
                "Run: pip install google-genai"
            ) from exc

        self._client = genai.Client(api_key=api_key)
        self._types = genai_types
        self._model = model
        self._cache: TTLCache[ArtworkQuery] = TTLCache(ttl_seconds=3600)
        self._fallback = DefaultIntentParser()

    async def parse(self, text: str) -> ArtworkQuery:
        cached = self._cache.get(text)
        if cached is not None:
            return cached

        try:
            result = await self._call_gemini(text)
        except Exception as exc:
            logger.warning("Gemini intent parse failed (%s), using fallback", exc)
            result = await self._fallback.parse(text)

        self._cache.set(text, result)
        return result

    async def _call_gemini(self, text: str) -> ArtworkQuery:
        config = self._types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=_ParsedIntent,
        )
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=text,
            config=config,
        )
        if not response.text:
            raise ValueError("Empty response from Gemini")

        parsed = _ParsedIntent.model_validate_json(response.text)
        confidence = max(0.0, min(1.0, parsed.confidence))  # clamp to [0, 1]

        return ArtworkQuery(
            raw_text=text,
            title=parsed.title,
            artist=parsed.artist,
            period=parsed.period,
            style=parsed.style,
            medium=parsed.medium,
            keywords=parsed.keywords,
            confidence=confidence,
            ambiguity_dimensions=parsed.ambiguity_dimensions,
        )


# ---------------------------------------------------------------------------
# Rule-based fallback (original implementation, preserved)
# ---------------------------------------------------------------------------

_ALIAS_RULES = [
    {
        "terms": ["pearl earring", "珍珠耳环", "戴珍珠耳环"],
        "title": "Girl with a Pearl Earring",
        "artist": "Johannes Vermeer",
        "keywords": ["girl", "pearl", "earring", "portrait", "vermeer"],
    },
    {
        "terms": ["mona lisa", "la gioconda", "蒙娜丽莎"],
        "title": "Mona Lisa",
        "artist": "Leonardo da Vinci",
        "keywords": ["portrait", "woman", "smile", "leonardo"],
    },
    {
        "terms": ["starry night", "星月夜", "星空"],
        "title": "The Starry Night",
        "artist": "Vincent van Gogh",
        "keywords": ["night", "stars", "village", "cypress", "van gogh"],
    },
    {
        "terms": ["sunflowers", "向日葵"],
        "title": "Sunflowers",
        "artist": "Vincent van Gogh",
        "keywords": ["flowers", "sunflowers", "yellow", "van gogh"],
    },
    {
        "terms": ["great wave", "kanagawa", "神奈川", "冲浪"],
        "title": "The Great Wave off Kanagawa",
        "artist": "Katsushika Hokusai",
        "keywords": ["wave", "mount fuji", "sea", "woodblock", "hokusai"],
    },
    {
        "terms": ["the scream", "呐喊"],
        "title": "The Scream",
        "artist": "Edvard Munch",
        "keywords": ["scream", "bridge", "anxiety", "expressionism", "munch"],
    },
]


class DefaultIntentParser:
    """Deterministic rule-based parser; used as fallback when LLM is unavailable."""

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


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_intent_parser() -> LLMIntentParser | DefaultIntentParser:
    """Return LLMIntentParser if GEMINI_API_KEY is configured, else the rule-based fallback."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    if api_key:
        logger.info("Using Gemini intent parser (model=%s)", model)
        return LLMIntentParser(api_key=api_key, model=model)
    logger.info("GEMINI_API_KEY not set — using rule-based intent parser")
    return DefaultIntentParser()
