import { useQuery, useQueryClient } from '@tanstack/react-query'
import { clearHistory, fetchHistory } from '../lib/api'
import type { HistoryEntry } from '../types/api'

export function useHistory(sessionId: string | null) {
  const queryClient = useQueryClient()
  const queryKey = ['history', sessionId]

  const query = useQuery<HistoryEntry[], Error>({
    queryKey,
    queryFn: () => fetchHistory(sessionId!, 20),
    enabled: !!sessionId,
    staleTime: 30_000,   // re-fetch after 30s so new searches appear promptly
    gcTime: 5 * 60_000,
  })

  const clear = async () => {
    if (!sessionId) return
    await clearHistory(sessionId)
    queryClient.setQueryData(queryKey, [])
  }

  // Called by the search pipeline after a new search completes so the list
  // updates without waiting for the staleTime window.
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey })
  }

  return {
    history: query.data ?? [],
    isLoading: query.isLoading,
    clear,
    invalidate,
  }
}
