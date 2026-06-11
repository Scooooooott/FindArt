from __future__ import annotations

import logging
import os
import re
from typing import Protocol

from app.models import ArtworkQuery
from app.services.cache import TTLCache
from pydantic import BaseModel, ConfigDict, Field

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

Respond with a JSON object containing exactly the fields above. No extra keys, no markdown fences.
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
        cache_key = " ".join(text.split()).casefold()
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("Gemini intent cache hit for %r", text[:60])
            return cached

        logger.info("Gemini intent parse: model=%s text_len=%d", self._model, len(text))
        try:
            result = await self._call_gemini(text)
            logger.info(
                "Gemini intent parse OK: title=%r artist=%r confidence=%.2f",
                result.title, result.artist, result.confidence,
            )
        except Exception:
            logger.warning("Gemini intent parse failed — using rule-based fallback", exc_info=True)
            result = await self._fallback.parse(text)

        self._cache.set(cache_key, result)
        return result

    async def parse_image(self, image_base64: str, mime_type: str) -> ArtworkQuery:
        """Identify a painting from an uploaded image using Gemini Vision."""
        import hashlib
        cache_key = f"img:{hashlib.sha256(image_base64[:256].encode()).hexdigest()[:16]}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            result = await self._call_gemini_vision(image_base64, mime_type)
        except Exception as exc:
            logger.warning("Gemini vision parse failed (%s), returning generic query", exc)
            result = ArtworkQuery(raw_text="[image upload]", keywords=[], confidence=0.3)

        self._cache.set(cache_key, result)
        return result

    async def _call_gemini_vision(self, image_base64: str, mime_type: str) -> ArtworkQuery:
        import base64 as _base64
        image_bytes = _base64.b64decode(image_base64)
        image_part = self._types.Part(
            inline_data=self._types.Blob(mime_type=mime_type, data=image_bytes)
        )
        text_part = self._types.Part(text="Identify this painting and extract the artwork details.")

        config = self._types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=_ParsedIntent,
        )
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=[image_part, text_part],
            config=config,
        )
        if not response.text:
            raise ValueError("Empty response from Gemini Vision")

        parsed = _ParsedIntent.model_validate_json(response.text)
        confidence = max(0.0, min(1.0, parsed.confidence))

        return ArtworkQuery(
            raw_text="[image upload]",
            title=parsed.title,
            artist=parsed.artist,
            period=parsed.period,
            style=parsed.style,
            medium=parsed.medium,
            keywords=parsed.keywords,
            confidence=confidence,
            ambiguity_dimensions=parsed.ambiguity_dimensions,
        )

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
# DeepSeek (OpenAI-compatible) parser
# ---------------------------------------------------------------------------

class DeepSeekIntentParser:
    """DeepSeek-backed intent parser using the OpenAI-compatible API.

    Works with any OpenAI-compatible endpoint; defaults to DeepSeek.
    Falls back to DefaultIntentParser on any error.
    """

    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "openai package is not installed. Run: pip install openai"
            ) from exc

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._cache: TTLCache[ArtworkQuery] = TTLCache(ttl_seconds=3600)
        self._fallback = DefaultIntentParser()

    async def parse(self, text: str) -> ArtworkQuery:
        cache_key = " ".join(text.split()).casefold()
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("DeepSeek intent cache hit for %r", text[:60])
            return cached

        logger.info("DeepSeek intent parse: model=%s text_len=%d", self._model, len(text))
        try:
            result = await self._call_api(text)
            logger.info(
                "DeepSeek intent parse OK: title=%r artist=%r confidence=%.2f keywords=%s",
                result.title, result.artist, result.confidence, result.keywords[:3],
            )
        except Exception:
            logger.warning("DeepSeek intent parse failed — using rule-based fallback", exc_info=True)
            result = await self._fallback.parse(text)

        self._cache.set(cache_key, result)
        return result

    async def _call_api(self, text: str) -> ArtworkQuery:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": text},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        raw = response.choices[0].message.content
        if not raw:
            raise ValueError("Empty response from DeepSeek")

        parsed = _ParsedIntent.model_validate_json(raw)
        confidence = max(0.0, min(1.0, parsed.confidence))

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
# Factory
# ---------------------------------------------------------------------------

def create_intent_parser() -> DeepSeekIntentParser | LLMIntentParser | DefaultIntentParser:
    """Parser priority: DeepSeek → Gemini → rule-based fallback."""
    ds_key  = os.getenv("DEEPSEEK_API_KEY",  "").strip()
    ds_model = os.getenv("DEEPSEEK_MODEL",   "deepseek-chat").strip()
    ds_url  = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
    logger.info(
        "[intent] DEEPSEEK_API_KEY=%s  DEEPSEEK_MODEL=%s  DEEPSEEK_BASE_URL=%s",
        f"SET({len(ds_key)}chars)" if ds_key else "MISSING",
        ds_model,
        ds_url,
    )
    if ds_key:
        print(f"[intent] Using DeepSeek intent parser (model={ds_model})", flush=True)
        logger.info("Using DeepSeek intent parser (model=%s)", ds_model)
        return DeepSeekIntentParser(api_key=ds_key, model=ds_model, base_url=ds_url)

    gemini_key   = os.getenv("GEMINI_API_KEY", "").strip()
    gemini_model = os.getenv("GEMINI_MODEL",   "gemini-2.5-flash").strip()
    logger.info(
        "[intent] GEMINI_API_KEY=%s  GEMINI_MODEL=%s",
        f"SET({len(gemini_key)}chars)" if gemini_key else "MISSING",
        gemini_model,
    )
    if gemini_key:
        print(f"[intent] Using Gemini intent parser (model={gemini_model})", flush=True)
        logger.info("Using Gemini intent parser (model=%s)", gemini_model)
        return LLMIntentParser(api_key=gemini_key, model=gemini_model)

    print("[intent] WARNING: No LLM API key set — using rule-based intent parser", flush=True)
    logger.warning("[intent] No LLM API key set — using rule-based intent parser")
    return DefaultIntentParser()
