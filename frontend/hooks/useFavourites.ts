import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { addFavourite, fetchFavourites, removeFavourite } from '../lib/api'
import type { ArtworkCandidate, FavouriteEntry } from '../types/api'

export function useFavourites(sessionId: string | null) {
  const queryClient = useQueryClient()
  const queryKey = ['favourites', sessionId]

  const query = useQuery<FavouriteEntry[], Error>({
    queryKey,
    queryFn: () => fetchFavourites(sessionId!),
    enabled: !!sessionId,
    staleTime: 60_000,
    gcTime: 10 * 60_000,
  })

  // Build a Set for O(1) membership checks
  const favouriteKeys = new Set(
    (query.data ?? []).map(f => `${f.artwork_id}::${f.source_api}`)
  )

  const isFavourited = (candidate: ArtworkCandidate): boolean =>
    favouriteKeys.has(`${candidate.id}::${candidate.source_api}`)

  const toggle = useMutation<void, Error, ArtworkCandidate>({
    mutationFn: async (candidate) => {
      if (!sessionId) return
      if (isFavourited(candidate)) {
        await removeFavourite(sessionId, candidate.id, candidate.source_api)
      } else {
        await addFavourite(sessionId, candidate)
      }
    },

    // Optimistic update — flip the local cache before the request returns
    onMutate: async (candidate) => {
      await queryClient.cancelQueries({ queryKey })
      const snapshot = queryClient.getQueryData<FavouriteEntry[]>(queryKey)

      queryClient.setQueryData<FavouriteEntry[]>(queryKey, prev => {
        const list = prev ?? []
        const key = `${candidate.id}::${candidate.source_api}`
        if (favouriteKeys.has(key)) {
          // Remove
          return list.filter(
            f => !(f.artwork_id === candidate.id && f.source_api === candidate.source_api)
          )
        }
        // Add (prepend so it appears at the top)
        return [
          {
            artwork_id: candidate.id,
            source_api: candidate.source_api,
            candidate,
            created_at: new Date().toISOString(),
          },
          ...list,
        ]
      })

      return { snapshot }
    },

    // Roll back on error
    onError: (_err, _candidate, context: any) => {
      if (context?.snapshot !== undefined) {
        queryClient.setQueryData(queryKey, context.snapshot)
      }
    },

    // Always reconcile with the server after settle
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey })
    },
  })

  return {
    favourites: query.data ?? [],
    isFavourited,
    toggleFavourite: toggle.mutate,
    isLoading: query.isLoading,
  }
}
