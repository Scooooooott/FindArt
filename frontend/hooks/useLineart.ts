import { useQuery } from '@tanstack/react-query'
import { generateLineart } from '../lib/api'

export function useLineart(imageUrl: string | null, mode: 'canny' | 'fine' = 'fine') {
  return useQuery({
    queryKey: ['lineart', imageUrl, mode],
    queryFn: () => generateLineart(imageUrl!, mode),
    enabled: !!imageUrl,
    staleTime: Infinity,
    gcTime: 60 * 60 * 1000,
    retry: 1,
  })
}
