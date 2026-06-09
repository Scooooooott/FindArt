import { useState, useEffect } from 'react'
import {
  View, Text, ScrollView, StyleSheet, TouchableOpacity, TextInput,
  ActivityIndicator, Platform, KeyboardAvoidingView,
} from 'react-native'
import { router } from 'expo-router'
import { useQueryClient } from '@tanstack/react-query'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { SearchBar } from '../components/SearchBar'
import { ViewToggle, type ViewMode } from '../components/ViewToggle'
import { ThumbnailCard } from '../components/ThumbnailCard'
import { ThumbnailRow } from '../components/ThumbnailRow'
import { SkeletonCard } from '../components/SkeletonCard'
import { useSearch } from '../hooks/useSearch'
import { useImageSearch } from '../hooks/useImageSearch'
import { useHistory } from '../hooks/useHistory'
import { useFavourites } from '../hooks/useFavourites'
import { useSessionId } from '../contexts/SessionContext'
import { ImageSearchButton } from '../components/ImageSearchButton'
import { colors } from '../constants/colors'
import type { ArtworkCandidate, ArtworkQuery, HistoryEntry } from '../types/api'

const SKELETON_COUNT = 6
const MAX_CLARIFICATION_ROUNDS = 2

// ---------------------------------------------------------------------------
// Recent searches chip strip
// ---------------------------------------------------------------------------

function HistoryChips({ history, onSelect, onClear }: {
  history: HistoryEntry[]
  onSelect: (text: string) => void
  onClear: () => void
}) {
  if (history.length === 0) return null
  return (
    <View style={histStyles.container}>
      <View style={histStyles.header}>
        <Text style={histStyles.label}>Recent searches</Text>
        <TouchableOpacity onPress={onClear} hitSlop={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <Text style={histStyles.clearText}>Clear</Text>
        </TouchableOpacity>
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={histStyles.scroll}>
        {history.slice(0, 8).map((entry, i) => (
          <TouchableOpacity
            key={i}
            style={histStyles.chip}
            onPress={() => onSelect(entry.query_text)}
            activeOpacity={0.75}
          >
            <Text style={histStyles.chipText} numberOfLines={1}>{entry.query_text}</Text>
          </TouchableOpacity>
        ))}
      </ScrollView>
    </View>
  )
}

function IntentCard({ parsedQuery, loading }: { parsedQuery: ArtworkQuery; loading: boolean }) {
  const confidence = parsedQuery.confidence
  const confidenceLabel = confidence >= 0.8 ? 'High confidence' : confidence >= 0.5 ? 'Medium confidence' : 'Low confidence'
  const mainText = parsedQuery.title
    ? `《${parsedQuery.title}》`
    : parsedQuery.keywords.slice(0, 3).join(' · ')
  const meta = [parsedQuery.style, parsedQuery.period].filter(Boolean).join(' · ')

  return (
    <View style={intentStyles.card}>
      <View style={intentStyles.row}>
        <Text style={intentStyles.label}>AI</Text>
        <Text style={intentStyles.confidence}>{confidenceLabel}</Text>
        <View style={{ flex: 1 }} />
        {loading && <ActivityIndicator size="small" color={colors.textMuted} />}
      </View>
      <Text style={intentStyles.main}>{mainText}</Text>
      {parsedQuery.artist ? <Text style={intentStyles.artist}>{parsedQuery.artist}</Text> : null}
      {meta ? <Text style={intentStyles.meta}>{meta}</Text> : null}
    </View>
  )
}

export default function SearchScreen() {
  const insets = useSafeAreaInsets()
  const queryClient = useQueryClient()
  const sessionId = useSessionId()
  const [query, setQuery] = useState('')
  const [viewMode, setViewMode] = useState<ViewMode>('grid')
  const [roundCount, setRoundCount] = useState(0)
  const [clarificationInput, setClarificationInput] = useState('')
  const [imageMode, setImageMode] = useState(false)

  const {
    parsedQuery,
    candidates,
    diagnostics,
    clarification: rawClarification,
    intentLoading,
    candidatesLoading,
    isError,
    error,
    refetch,
  } = useSearch(query)

  const { history, clear: clearHistory, invalidate: invalidateHistory } = useHistory(sessionId)
  const { isFavourited, toggleFavourite } = useFavourites(sessionId)
  const { candidates: imageCandidates, loading: imageLoading, error: imageError, pickAndSearch, clear: clearImage } = useImageSearch()

  const isLoading = intentLoading || candidatesLoading
  const fallbackMode = diagnostics?.fallback_mode ?? null
  const clarification = roundCount < MAX_CLARIFICATION_ROUNDS ? (rawClarification ?? null) : null

  const displayCandidates = imageMode ? imageCandidates : candidates
  const displayLoading = imageMode ? imageLoading : isLoading

  useEffect(() => {
    if (imageLoading || imageCandidates.length > 0) setImageMode(true)
  }, [imageLoading, imageCandidates.length])

  const handleSearch = (text: string) => {
    setQuery(text)
    setRoundCount(0)
    setClarificationInput('')
    setImageMode(false)
    clearImage()
    setTimeout(invalidateHistory, 4000)
  }

  const handleClarify = () => {
    const answer = clarificationInput.trim()
    if (!answer) return
    setQuery(q => q + '，' + answer)
    setRoundCount(r => r + 1)
    setClarificationInput('')
  }

  const handleSelect = (candidate: ArtworkCandidate) => {
    queryClient.setQueryData(['candidate', candidate.id], candidate)
    router.push({
      pathname: '/artwork/[id]',
      params: { id: candidate.id },
    })
  }

  const toolbarLabel = imageMode
    ? (imageLoading ? 'Analyzing image...' : `${imageCandidates.length} artworks`)
    : intentLoading
    ? 'Identifying...'
    : candidatesLoading
    ? 'Searching...'
    : `${candidates.length} artworks`

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'android' ? 'height' : undefined}
    >
      {/* ── Header ── */}
      <View style={[styles.header, { paddingTop: Platform.OS === 'web' ? 56 : insets.top + 16 }]}>
        <View style={styles.logoRow}>
          <Text style={styles.logo}>FindArt</Text>
          <TouchableOpacity onPress={() => router.push('/explore')} activeOpacity={0.7}>
            <Text style={styles.browseLink}>Browse →</Text>
          </TouchableOpacity>
        </View>
        <Text style={styles.tagline}>Describe a painting to find its high-res original</Text>
        <View style={styles.searchRow}>
          <View style={{ flex: 1 }}>
            <SearchBar onSearch={handleSearch} loading={!imageMode && isLoading} />
          </View>
          <ImageSearchButton onPress={pickAndSearch} loading={imageLoading} active={imageMode} />
        </View>
      </View>

      {/* ── Toolbar ── */}
      {(displayCandidates.length > 0 || displayLoading) && (
        <View style={styles.toolbar}>
          <Text style={styles.resultCount}>{toolbarLabel}</Text>
          {imageMode && (
            <TouchableOpacity
              style={styles.imageModeTag}
              onPress={() => { setImageMode(false); clearImage() }}
              hitSlop={{ top: 4, right: 4, bottom: 4, left: 4 }}
              activeOpacity={0.7}
            >
              <Text style={styles.imageModeText}>Image search  ✕</Text>
            </TouchableOpacity>
          )}
          <ViewToggle mode={viewMode} onChange={setViewMode} />
        </View>
      )}

      {/* ── Results ── */}
      <ScrollView style={styles.scroll} contentContainerStyle={styles.scrollContent} keyboardShouldPersistTaps="handled">
        {(isError || imageError != null) && (
          <View style={styles.stateBox}>
            <Text style={styles.stateIcon}>⚠️</Text>
            <Text style={styles.stateTitle}>Search failed</Text>
            <Text style={styles.stateMsg}>{(imageError ?? error)?.message}</Text>
            {!imageMode && (
              <TouchableOpacity style={styles.retryBtn} onPress={refetch}>
                <Text style={styles.retryText}>Retry</Text>
              </TouchableOpacity>
            )}
          </View>
        )}

        {imageMode && !imageLoading && imageCandidates.length === 0 && !imageError && (
          <View style={styles.stateBox}>
            <Text style={styles.stateIcon}>🖼</Text>
            <Text style={styles.stateTitle}>No artworks found</Text>
            <Text style={styles.stateMsg}>Try a different image, or search by text description</Text>
            <TouchableOpacity style={styles.retryBtn} onPress={() => { setImageMode(false); clearImage() }}>
              <Text style={styles.retryText}>Back to search</Text>
            </TouchableOpacity>
          </View>
        )}

        {!imageMode && !isLoading && !isError && query.trim().length > 1 && candidates.length === 0 && (
          <View style={styles.stateBox}>
            <Text style={styles.stateIcon}>🔍</Text>
            <Text style={styles.stateTitle}>No matching artworks found</Text>
            <Text style={styles.stateMsg}>Try a different description — add artist, period, or style</Text>
            <TouchableOpacity
              style={styles.exploreBtn}
              onPress={() => router.push('/explore')}
              activeOpacity={0.7}
            >
              <Text style={styles.exploreBtnText}>Browse by Style</Text>
            </TouchableOpacity>
          </View>
        )}

        {!imageMode && !query && (
          <View>
            <View style={styles.stateBox}>
              <Text style={styles.stateIcon}>🎨</Text>
              <Text style={styles.stateTitle}>Enter a description above</Text>
              <Text style={styles.stateMsg}>Describe the subject, artist, period, or style</Text>
            </View>
            <HistoryChips
              history={history}
              onSelect={handleSearch}
              onClear={clearHistory}
            />
          </View>
        )}

        {/* AI intent card — appears as soon as M1 returns, before candidates arrive */}
        {!imageMode && parsedQuery && query.trim().length > 1 && (
          <IntentCard parsedQuery={parsedQuery} loading={candidatesLoading} />
        )}

        {/* Fallback notice */}
        {!imageMode && fallbackMode && candidates.length > 0 && (
          <View style={styles.fallbackNotice}>
            <Text style={styles.fallbackText}>No exact match — showing related artworks</Text>
          </View>
        )}

        {/* Grid view */}
        {viewMode === 'grid' && (
          <View style={styles.grid}>
            {displayLoading
              ? Array.from({ length: SKELETON_COUNT }).map((_, i) => (
                  <SkeletonCard key={i} mode="grid" />
                ))
              : displayCandidates.map(c => (
                  <ThumbnailCard
                    key={c.id}
                    candidate={c}
                    onPress={() => handleSelect(c)}
                    isFavourited={isFavourited(c)}
                    onToggleFavourite={() => toggleFavourite(c)}
                  />
                ))}
          </View>
        )}

        {/* List view */}
        {viewMode === 'list' && (
          <View>
            {displayLoading
              ? Array.from({ length: SKELETON_COUNT }).map((_, i) => (
                  <SkeletonCard key={i} mode="list" />
                ))
              : displayCandidates.map(c => (
                  <ThumbnailRow
                    key={c.id}
                    candidate={c}
                    onPress={() => handleSelect(c)}
                    isFavourited={isFavourited(c)}
                    onToggleFavourite={() => toggleFavourite(c)}
                  />
                ))}
          </View>
        )}

        {/* Clarification card */}
        {!imageMode && clarification && !isLoading && (
          <View style={styles.clarificationCard}>
            <Text style={styles.clarificationLabel}>A more specific description improves results</Text>
            <Text style={styles.clarificationQuestion}>{clarification.question}</Text>
            <View style={styles.clarificationRow}>
              <TextInput
                style={styles.clarificationInput}
                value={clarificationInput}
                onChangeText={setClarificationInput}
                placeholder="Add more detail..."
                placeholderTextColor={colors.textMuted}
                onSubmitEditing={handleClarify}
                returnKeyType="search"
              />
              <TouchableOpacity
                style={[styles.clarificationBtn, !clarificationInput.trim() && styles.clarificationBtnDisabled]}
                onPress={handleClarify}
                disabled={!clarificationInput.trim()}
                activeOpacity={0.7}
              >
                <Text style={styles.clarificationBtnText}>Submit</Text>
              </TouchableOpacity>
            </View>
            {roundCount > 0 && (
              <Text style={styles.clarificationRound}>Round {roundCount} of {MAX_CLARIFICATION_ROUNDS}</Text>
            )}
          </View>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bg,
  },
  header: {
    paddingHorizontal: 20,
    paddingBottom: 16,
    gap: 6,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderColor: colors.border,
  },
  logoRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  logo: {
    fontSize: 26,
    fontWeight: '700',
    color: colors.textPrimary,
    letterSpacing: -0.5,
  },
  browseLink: {
    fontSize: 13,
    color: colors.textSecondary,
  },
  tagline: {
    fontSize: 13,
    color: colors.textSecondary,
    marginBottom: 6,
  },
  searchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  toolbar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 10,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderColor: colors.border,
  },
  resultCount: {
    fontSize: 13,
    color: colors.textSecondary,
    flex: 1,
  },
  imageModeTag: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 8,
    paddingVertical: 4,
    backgroundColor: colors.accent,
    borderRadius: 12,
    marginRight: 8,
  },
  imageModeText: {
    fontSize: 11,
    color: colors.surface,
    fontWeight: '600',
  },
  scroll: {
    flex: 1,
  },
  scrollContent: {
    padding: 6,
    flexGrow: 1,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  fallbackNotice: {
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  fallbackText: {
    fontSize: 12,
    color: colors.textMuted,
    fontStyle: 'italic',
  },
  clarificationCard: {
    marginHorizontal: 6,
    marginTop: 16,
    marginBottom: 8,
    padding: 14,
    backgroundColor: colors.surface,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 8,
  },
  clarificationLabel: {
    fontSize: 11,
    color: colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  clarificationQuestion: {
    fontSize: 14,
    color: colors.textPrimary,
    fontWeight: '500',
    lineHeight: 20,
  },
  clarificationRow: {
    flexDirection: 'row',
    gap: 8,
  },
  clarificationInput: {
    flex: 1,
    height: 40,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 7,
    paddingHorizontal: 12,
    fontSize: 14,
    color: colors.textPrimary,
    backgroundColor: colors.bg,
    ...(Platform.OS === 'web' ? { outlineStyle: 'none' } : {}),
  } as any,
  clarificationBtn: {
    height: 40,
    paddingHorizontal: 16,
    backgroundColor: colors.accent,
    borderRadius: 7,
    alignItems: 'center',
    justifyContent: 'center',
  },
  clarificationBtnDisabled: {
    opacity: 0.4,
  },
  clarificationBtnText: {
    color: colors.surface,
    fontSize: 14,
    fontWeight: '600',
  },
  clarificationRound: {
    fontSize: 11,
    color: colors.textMuted,
    textAlign: 'right',
  },
  stateBox: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 40,
    gap: 8,
  },
  stateIcon: {
    fontSize: 40,
    marginBottom: 8,
  },
  stateTitle: {
    fontSize: 17,
    fontWeight: '600',
    color: colors.textPrimary,
    textAlign: 'center',
  },
  stateMsg: {
    fontSize: 14,
    color: colors.textSecondary,
    textAlign: 'center',
    lineHeight: 20,
  },
  retryBtn: {
    marginTop: 12,
    paddingHorizontal: 20,
    paddingVertical: 8,
    backgroundColor: colors.accent,
    borderRadius: 7,
  },
  retryText: {
    color: colors.surface,
    fontSize: 14,
    fontWeight: '600',
  },
  exploreBtn: {
    marginTop: 12,
    paddingHorizontal: 20,
    paddingVertical: 8,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 7,
  },
  exploreBtnText: {
    fontSize: 14,
    color: colors.textSecondary,
  },
})

const histStyles = StyleSheet.create({
  container: {
    marginHorizontal: 6,
    marginTop: 4,
    marginBottom: 8,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 6,
    marginBottom: 8,
  },
  label: {
    fontSize: 11,
    color: colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  clearText: {
    fontSize: 11,
    color: colors.textMuted,
  },
  scroll: {
    paddingHorizontal: 4,
    gap: 8,
  },
  chip: {
    maxWidth: 200,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 16,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  chipText: {
    fontSize: 13,
    color: colors.textSecondary,
  },
})

const intentStyles = StyleSheet.create({
  card: {
    marginHorizontal: 6,
    marginTop: 8,
    marginBottom: 4,
    paddingHorizontal: 14,
    paddingVertical: 10,
    backgroundColor: colors.surface,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 3,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 2,
  },
  label: {
    fontSize: 11,
    color: colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  confidence: {
    fontSize: 11,
    color: colors.textMuted,
  },
  main: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.textPrimary,
  },
  artist: {
    fontSize: 13,
    color: colors.textSecondary,
  },
  meta: {
    fontSize: 11,
    color: colors.textMuted,
  },
})
