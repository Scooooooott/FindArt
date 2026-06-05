// Mirrors backend Pydantic models — keep in sync with backend/app/models.py

export interface ArtworkQuery {
  raw_text: string
  title: string | null
  artist: string | null
  period: string | null
  style: string | null
  medium: string | null
  keywords: string[]
  confidence: number
  ambiguity_dimensions: string[]
}

export interface ArtworkCandidate {
  id: string
  source_api: string
  title: string
  artist: string | null
  year: string | null
  medium: string | null
  thumbnail_url: string | null
  image_url: string | null
  iiif_base_url: string | null
  source_url: string | null
  detail_url: string | null
  wikidata_id: string | null
  is_public_domain: boolean | null
  license_status: string | null
  image_available: boolean | null
  score: number
  matched_sources: string[]
  metadata: Record<string, unknown>
}

export interface ClarificationHint {
  question: string
  dimension: string
}

export interface SearchDiagnostics {
  request_id: string
  timings_ms: Record<string, number>
  providers: string[]
  warnings: string[]
  fallback_mode: string | null
}

export interface SearchResponse {
  request_id: string
  query: ArtworkQuery
  candidates: ArtworkCandidate[]
  diagnostics: SearchDiagnostics
  clarification: ClarificationHint | null
}

export interface ArtworkImage {
  id: string
  source_api: string
  full_url: string
  medium_url: string
  iiif_base_url: string | null
  cached: boolean
}

// ---------------------------------------------------------------------------
// Session — history & favourites
// ---------------------------------------------------------------------------

export interface HistoryEntry {
  query_text: string
  parsed_query: ArtworkQuery | null
  result_count: number | null
  fallback_mode: string | null
  created_at: string
}

export interface FavouriteEntry {
  artwork_id: string
  source_api: string
  candidate: ArtworkCandidate
  created_at: string
}
