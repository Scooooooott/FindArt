import { useState, useCallback } from 'react'
import * as ImagePicker from 'expo-image-picker'
import { searchImage } from '../lib/api'
import type { ArtworkCandidate } from '../types/api'

export interface ImageSearchState {
  candidates: ArtworkCandidate[]
  loading: boolean
  error: Error | null
}

export function useImageSearch() {
  const [state, setState] = useState<ImageSearchState>({
    candidates: [],
    loading: false,
    error: null,
  })

  const pickAndSearch = useCallback(async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync()
    if (!perm.granted) return

    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: 'images',
      quality: 0.7,
      base64: true,
    })

    if (result.canceled || !result.assets?.[0]?.base64) return

    const asset = result.assets[0]
    const mimeType = asset.mimeType ?? 'image/jpeg'

    setState({ candidates: [], loading: true, error: null })
    try {
      const response = await searchImage(asset.base64!, mimeType)
      setState({ candidates: response.candidates, loading: false, error: null })
    } catch (err) {
      setState({ candidates: [], loading: false, error: err as Error })
    }
  }, [])

  const clear = useCallback(() => {
    setState({ candidates: [], loading: false, error: null })
  }, [])

  return { ...state, pickAndSearch, clear }
}
