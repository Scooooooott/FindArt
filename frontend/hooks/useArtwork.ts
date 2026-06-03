import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { ArtworkCandidate, ArtworkImage } from '../types/api'

export function useArtwork(candidate: ArtworkCandidate) {
  return useQuery<ArtworkImage, Error>({
    queryKey: ['artwork', candidate.id],
    queryFn: () => api.post<ArtworkImage>('/artworks/resolve-image', { candidate }),
    staleTime: Infinity, // image URLs for a given artwork don't change
    retry: 1,
  })
}
