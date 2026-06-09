import { useState } from 'react'
import {
  View, Text, ScrollView, StyleSheet, TouchableOpacity, Platform,
} from 'react-native'
import { router } from 'expo-router'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useQueryClient } from '@tanstack/react-query'
import { ThumbnailCard } from '../components/ThumbnailCard'
import { ThumbnailRow } from '../components/ThumbnailRow'
import { SkeletonCard } from '../components/SkeletonCard'
import { ViewToggle, type ViewMode } from '../components/ViewToggle'
import { useSearch } from '../hooks/useSearch'
import { useFavourites } from '../hooks/useFavourites'
import { useSessionId } from '../contexts/SessionContext'
import { colors } from '../constants/colors'
import type { ArtworkCandidate } from '../types/api'

// ---------------------------------------------------------------------------
// Curated browse categories — each maps to a vector search query.
// Labels and queries should match the movement/genre metadata in the Qdrant
// corpus (populated by scripts/ingest_wikidata.py sparql).
// ---------------------------------------------------------------------------

const CATEGORIES = [
  { id: 'impressionism',       label: 'Impressionism',        query: 'Impressionism Monet Renoir landscape' },
  { id: 'post-impressionism',  label: 'Post-Impressionism',   query: 'Post-Impressionism van Gogh Cézanne' },
  { id: 'surrealism',          label: 'Surrealism',           query: 'Surrealism dreamlike Dalí Magritte' },
  { id: 'dutch-golden-age',    label: 'Dutch Golden Age',     query: 'Dutch Golden Age Vermeer Rembrandt portrait' },
  { id: 'baroque',             label: 'Baroque',              query: 'Baroque Caravaggio dramatic chiaroscuro' },
  { id: 'renaissance',         label: 'Renaissance',          query: 'Renaissance Leonardo Raphael religious' },
  { id: 'romanticism',         label: 'Romanticism',          query: 'Romanticism Turner Delacroix landscape emotion' },
  { id: 'ukiyo-e',             label: 'Ukiyo-e',              query: 'Ukiyo-e Japanese woodblock Hokusai wave' },
  { id: 'expressionism',       label: 'Expressionism',        query: 'Expressionism Munch Kirchner emotion' },
  { id: 'modernism',           label: 'Modernism',            query: 'Modernism abstract Kandinsky Klee Matisse' },
  { id: 'realism',             label: 'Realism',              query: 'Realism Courbet everyday scene' },
  { id: 'symbolism',           label: 'Symbolism',            query: 'Symbolism Klimt Moreau allegorical' },
] as const

const SKELETON_COUNT = 6

export default function ExploreScreen() {
  const insets = useSafeAreaInsets()
  const queryClient = useQueryClient()
  const sessionId = useSessionId()
  const [activeCategory, setActiveCategory] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>('grid')

  const activeQuery = CATEGORIES.find(c => c.id === activeCategory)?.query ?? ''
  const { candidates, intentLoading, candidatesLoading } = useSearch(activeQuery)
  const { isFavourited, toggleFavourite } = useFavourites(sessionId)

  const isLoading = intentLoading || candidatesLoading

  const handleSelect = (candidate: ArtworkCandidate) => {
    queryClient.setQueryData(['candidate', candidate.id], candidate)
    router.push({ pathname: '/artwork/[id]', params: { id: candidate.id } })
  }

  return (
    <View style={styles.container}>
      {/* ── Header ── */}
      <View style={[styles.header, { paddingTop: Platform.OS === 'web' ? 56 : insets.top + 16 }]}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <Text style={styles.backText}>← Back</Text>
        </TouchableOpacity>
        <Text style={styles.title}>Browse by Style</Text>
        <View style={{ width: 52 }} />
      </View>

      {/* ── Category chips ── */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.chipsScroll}
        contentContainerStyle={styles.chipsContent}
      >
        {CATEGORIES.map(cat => {
          const active = activeCategory === cat.id
          return (
            <TouchableOpacity
              key={cat.id}
              style={[styles.chip, active && styles.chipActive]}
              onPress={() => setActiveCategory(active ? null : cat.id)}
              activeOpacity={0.75}
            >
              <Text style={[styles.chipText, active && styles.chipTextActive]}>
                {cat.label}
              </Text>
            </TouchableOpacity>
          )
        })}
      </ScrollView>

      {/* ── Results or empty state ── */}
      {!activeCategory ? (
        <View style={styles.emptyState}>
          <Text style={styles.emptyIcon}>🎨</Text>
          <Text style={styles.emptyTitle}>Pick a style to explore</Text>
          <Text style={styles.emptyMsg}>
            Tap a movement above to browse paintings from the curated collection
          </Text>
        </View>
      ) : (
        <>
          {/* Toolbar */}
          <View style={styles.toolbar}>
            <Text style={styles.resultCount}>
              {isLoading ? 'Searching…' : `${candidates.length} artworks`}
            </Text>
            <ViewToggle mode={viewMode} onChange={setViewMode} />
          </View>

          <ScrollView style={styles.scroll} contentContainerStyle={styles.scrollContent}>
            {!isLoading && candidates.length === 0 && (
              <View style={styles.emptyState}>
                <Text style={styles.emptyIcon}>🔍</Text>
                <Text style={styles.emptyTitle}>No results yet</Text>
                <Text style={styles.emptyMsg}>
                  Run the vector ingest script to populate the style corpus
                </Text>
              </View>
            )}

            {viewMode === 'grid' && (
              <View style={styles.grid}>
                {isLoading
                  ? Array.from({ length: SKELETON_COUNT }).map((_, i) => (
                      <SkeletonCard key={i} mode="grid" />
                    ))
                  : candidates.map(c => (
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

            {viewMode === 'list' && (
              <View>
                {isLoading
                  ? Array.from({ length: SKELETON_COUNT }).map((_, i) => (
                      <SkeletonCard key={i} mode="list" />
                    ))
                  : candidates.map(c => (
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
          </ScrollView>
        </>
      )}
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bg,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingBottom: 12,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderColor: colors.border,
  },
  backText: {
    fontSize: 15,
    color: colors.textSecondary,
    width: 52,
  },
  title: {
    fontSize: 17,
    fontWeight: '600',
    color: colors.textPrimary,
  },
  chipsScroll: {
    flexGrow: 0,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderColor: colors.border,
  },
  chipsContent: {
    paddingHorizontal: 16,
    paddingVertical: 12,
    gap: 8,
  },
  chip: {
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.bg,
  },
  chipActive: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  chipText: {
    fontSize: 13,
    color: colors.textSecondary,
  },
  chipTextActive: {
    color: colors.surface,
    fontWeight: '600',
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
  emptyState: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 40,
    gap: 8,
  },
  emptyIcon: {
    fontSize: 40,
    marginBottom: 8,
  },
  emptyTitle: {
    fontSize: 17,
    fontWeight: '600',
    color: colors.textPrimary,
    textAlign: 'center',
  },
  emptyMsg: {
    fontSize: 14,
    color: colors.textSecondary,
    textAlign: 'center',
    lineHeight: 20,
  },
})
