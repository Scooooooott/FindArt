import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { SearchResponse } from '../types/api'

export function useSearch(text: string) {
  return useQuery<SearchResponse, Error>({
    queryKey: ['search', text],
    queryFn: () => api.post<SearchResponse>('/search', { text, limit: 8 }),
    enabled: text.trim().length > 1,
    staleTime: 1000 * 60 * 60, // 1 hour — matches M1 cache TTL
    retry: 1,
  })
}
