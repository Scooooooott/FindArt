from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ArtworkQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_text: str = Field(min_length=1)
    title: str | None = None
    artist: str | None = None
    period: str | None = None
    style: str | None = None
    medium: str | None = None
    keywords: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ArtworkCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_api: str
    provider_id: str | None = None
    provider_object_id: str | None = None
    provider_image_id: str | None = None
    title: str
    artist: str | None = None
    year: str | None = None
    medium: str | None = None
    thumbnail_url: str | None = None
    source_url: str | None = None
    detail_url: str | None = None
    image_url: str | None = None
    iiif_base_url: str | None = None
    wikidata_id: str | None = None
    wikidata_url: str | None = None
    commons_filename: str | None = None
    is_public_domain: bool | None = None
    license_status: str | None = None
    image_available: bool | None = None
    free_image_available: bool | None = None
    rights_notice: str | None = None
    image_refs: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    score: float = 0.0
    matched_sources: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtworkImage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_api: str
    full_url: str
    medium_url: str
    iiif_base_url: str | None = None
    cached: bool = False


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=8, ge=1, le=20)


class SearchDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    timings_ms: dict[str, float] = Field(default_factory=dict)
    providers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    query: ArtworkQuery
    candidates: list[ArtworkCandidate]
    diagnostics: SearchDiagnostics


class ResolveImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate: ArtworkCandidate | None = None
    source_api: str | None = None
    id: str | None = None

    @model_validator(mode="after")
    def require_candidate_or_identity(self) -> "ResolveImageRequest":
        if self.candidate is None and not (self.source_api and self.id):
            raise ValueError("Provide either candidate or both source_api and id.")
        return self
