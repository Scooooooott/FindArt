import { useState, useEffect, useRef } from 'react'
import { streamSearch } from '../lib/api'
import type { ArtworkQuery, ArtworkCandidate, SearchDiagnostics, ClarificationHint, SearchResponse } from '../types/api'

interface SearchState {
  parsedQuery: ArtworkQuery | null
  candidates: ArtworkCandidate[]
  diagnostics: SearchDiagnostics | null
  clarification: ClarificationHint | null
  intentLoading: boolean
  candidatesLoading: boolean
  isError: boolean
  error: Error | null
  refetch: () => void
}

const IDLE_STATE = {
  parsedQuery: null,
  candidates: [],
  diagnostics: null,
  clarification: null,
  intentLoading: false,
  candidatesLoading: false,
  isError: false,
  error: null,
}

interface CacheEntry {
  parsedQuery: ArtworkQuery
  candidates: ArtworkCandidate[]
  diagnostics: SearchDiagnostics
  clarification: ClarificationHint | null
  timestamp: number
}

const CACHE_TTL_MS = 60 * 60 * 1000  // matches backend M1 cache TTL
const _cache = new Map<string, CacheEntry>()

export function useSearch(text: string): SearchState {
  const [state, setState] = useState(IDLE_STATE)
  const [retryKey, setRetryKey] = useState(0)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    const trimmed = text.trim()
    if (trimmed.length <= 1) {
      setState(IDLE_STATE)
      return
    }

    // Check cache (cleared on retry)
    if (retryKey === 0) {
      const cached = _cache.get(trimmed)
      if (cached && Date.now() - cached.timestamp < CACHE_TTL_MS) {
        setState({
          parsedQuery: cached.parsedQuery,
          candidates: cached.candidates,
          diagnostics: cached.diagnostics,
          clarification: cached.clarification,
          intentLoading: false,
          candidatesLoading: false,
          isError: false,
          error: null,
        })
        return
      }
    } else {
      _cache.delete(trimmed)
    }

    // Cancel any in-flight request
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setState({ ...IDLE_STATE, intentLoading: true, candidatesLoading: true })

    streamSearch(
      trimmed,
      8,
      controller.signal,
      (parsedQuery) => {
        setState(s => ({ ...s, parsedQuery, intentLoading: false }))
      },
      (response: SearchResponse) => {
        const entry: CacheEntry = {
          parsedQuery: response.query,
          candidates: response.candidates,
          diagnostics: response.diagnostics,
          clarification: response.clarification,
          timestamp: Date.now(),
        }
        _cache.set(trimmed, entry)
        setState({
          parsedQuery: response.query,
          candidates: response.candidates,
          diagnostics: response.diagnostics,
          clarification: response.clarification,
          intentLoading: false,
          candidatesLoading: false,
          isError: false,
          error: null,
        })
      },
    ).catch(err => {
      if ((err as Error)?.name === 'AbortError') return
      setState(s => ({
        ...s,
        intentLoading: false,
        candidatesLoading: false,
        isError: true,
        error: err instanceof Error ? err : new Error(String(err)),
      }))
    })

    return () => { controller.abort() }
  }, [text, retryKey])

  return { ...state, refetch: () => setRetryKey(k => k + 1) }
}
