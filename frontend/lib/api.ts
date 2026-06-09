import { Platform } from 'react-native'
import type { ArtworkCandidate, ArtworkQuery, FavouriteEntry, HistoryEntry, SearchResponse } from '../types/api'

// Android emulator maps 10.0.2.2 → dev machine localhost; real device needs LAN IP via EXPO_PUBLIC_API_URL
const _defaultUrl = Platform.OS === 'android' ? 'http://10.0.2.2:8000' : 'http://localhost:8000'
const BASE_URL = process.env.EXPO_PUBLIC_API_URL ?? _defaultUrl

// ---------------------------------------------------------------------------
// Session header injection
// ---------------------------------------------------------------------------

let _sessionId: string | null = null

/** Called by SessionProvider once the UUID is ready. */
export function setSessionId(id: string): void {
  _sessionId = id
}

function sessionHeaders(): Record<string, string> {
  return _sessionId ? { 'X-Session-ID': _sessionId } : {}
}

// ---------------------------------------------------------------------------
// Core HTTP helpers
// ---------------------------------------------------------------------------

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...sessionHeaders() },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`API ${res.status}: ${text || res.statusText}`)
  }
  return res.json() as Promise<T>
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: sessionHeaders(),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`API ${res.status}: ${text || res.statusText}`)
  }
  return res.json() as Promise<T>
}

async function del(path: string): Promise<void> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'DELETE',
    headers: sessionHeaders(),
  })
  if (!res.ok && res.status !== 204) {
    const text = await res.text().catch(() => '')
    throw new Error(`API ${res.status}: ${text || res.statusText}`)
  }
}

// ---------------------------------------------------------------------------
// Style transfer
// ---------------------------------------------------------------------------

export async function generateLineart(imageUrl: string, mode: 'canny' | 'fine' = 'fine'): Promise<string> {
  const { lineart_b64 } = await post<{ lineart_b64: string }>('/artworks/lineart', { image_url: imageUrl, mode })
  return `data:image/png;base64,${lineart_b64}`
}

export async function searchImage(
  imageBase64: string,
  mimeType: string,
  limit = 8,
): Promise<SearchResponse> {
  return post<SearchResponse>('/search/image', { image_base64: imageBase64, mime_type: mimeType, limit })
}

// ---------------------------------------------------------------------------
// SSE streaming search
// ---------------------------------------------------------------------------

/**
 * POST-based SSE stream for /search/stream.
 * Calls onIntent when AI parsing completes, onResult when candidates arrive.
 * Pass an AbortSignal to cancel mid-flight (e.g. when the query changes).
 */
export async function streamSearch(
  text: string,
  limit: number,
  signal: AbortSignal,
  onIntent: (query: ArtworkQuery) => void,
  onResult: (response: SearchResponse) => void,
): Promise<void> {
  const res = await fetch(`${BASE_URL}/search/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...sessionHeaders() },
    body: JSON.stringify({ text, limit }),
    signal,
  })

  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`API ${res.status}: ${body || res.statusText}`)
  }

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const data = line.slice(6).trim()
      if (!data) continue

      let event: any
      try {
        event = JSON.parse(data)
      } catch {
        continue
      }

      if (event.type === 'intent') onIntent(event.query as ArtworkQuery)
      else if (event.type === 'result') onResult(event as SearchResponse)
      else if (event.type === 'error') throw new Error(event.message as string)
    }
  }
}

// ---------------------------------------------------------------------------
// Session — history
// ---------------------------------------------------------------------------

export async function fetchHistory(sessionId: string, limit = 20): Promise<HistoryEntry[]> {
  const data = await get<{ history: HistoryEntry[] }>(
    `/sessions/${encodeURIComponent(sessionId)}/history?limit=${limit}`
  )
  return data.history
}

export async function clearHistory(sessionId: string): Promise<void> {
  await del(`/sessions/${encodeURIComponent(sessionId)}/history`)
}

// ---------------------------------------------------------------------------
// Session — favourites
// ---------------------------------------------------------------------------

export async function fetchFavourites(sessionId: string): Promise<FavouriteEntry[]> {
  const data = await get<{ favourites: FavouriteEntry[] }>(
    `/sessions/${encodeURIComponent(sessionId)}/favourites`
  )
  return data.favourites
}

export async function addFavourite(sessionId: string, candidate: ArtworkCandidate): Promise<void> {
  await post(`/sessions/${encodeURIComponent(sessionId)}/favourites`, { candidate })
}

export async function removeFavourite(
  sessionId: string,
  artworkId: string,
  sourceApi: string,
): Promise<void> {
  await del(
    `/sessions/${encodeURIComponent(sessionId)}/favourites/${encodeURIComponent(artworkId)}/${encodeURIComponent(sourceApi)}`
  )
}

export async function deleteSession(sessionId: string): Promise<void> {
  await del(`/sessions/${encodeURIComponent(sessionId)}`)
}

// ---------------------------------------------------------------------------
// Legacy named export kept for useArtwork compatibility
// ---------------------------------------------------------------------------

export const api = { post }
