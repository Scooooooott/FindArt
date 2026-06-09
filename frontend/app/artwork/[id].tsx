import { useLocalSearchParams, router } from 'expo-router'
import { View, Text, TouchableOpacity, StyleSheet, ScrollView, Platform, Image } from 'react-native'
import { StatusBar } from 'expo-status-bar'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useQueryClient } from '@tanstack/react-query'
import { useArtwork } from '../../hooks/useArtwork'
import { useSearch } from '../../hooks/useSearch'
import { ZoomableImage } from '../../components/ZoomableImage'
import { colors } from '../../constants/colors'
import type { ArtworkCandidate } from '../../types/api'

const _EMPTY_CANDIDATE: ArtworkCandidate = {
  id: '', source_api: '', title: '', artist: null, year: null, medium: null,
  thumbnail_url: null, image_url: null, iiif_base_url: null, source_url: null,
  detail_url: null, wikidata_id: null, is_public_domain: null, license_status: null,
  image_available: null, score: 0, matched_sources: [], metadata: {},
}

export default function ArtworkScreen() {
  const params = useLocalSearchParams<{ id: string }>()
  const insets = useSafeAreaInsets()
  const queryClient = useQueryClient()
  const candidate: ArtworkCandidate =
    queryClient.getQueryData<ArtworkCandidate>(['candidate', params.id])
    ?? _EMPTY_CANDIDATE
  const { data: artwork, isLoading, isError } = useArtwork(candidate)

  const movement = typeof candidate.metadata?.movement === 'string' ? candidate.metadata.movement : ''
  const similarQuery = [candidate.artist, movement].filter(Boolean).join(' ')
  const { candidates: similarCandidates, candidatesLoading: similarLoading } = useSearch(similarQuery)
  const relatedCandidates = similarCandidates.filter(c => c.id !== candidate.id).slice(0, 6)

  const displayUrl = artwork?.medium_url ?? candidate.image_url ?? candidate.thumbnail_url

  const meta = [candidate.year, candidate.medium]
    .filter(Boolean)
    .join(' · ')

  return (
    <View style={styles.container}>
      <StatusBar style="light" />

      {/* ── Header ── */}
      <View style={[styles.header, { paddingTop: Platform.OS === 'web' ? 52 : insets.top + 12 }]}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} activeOpacity={0.7}>
          <Text style={styles.backText}>← Back</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle} numberOfLines={1}>
          {candidate.title}
        </Text>
        <View style={styles.headerSpacer} />
      </View>

      {/* ── Image Viewer ── */}
      <View style={styles.imageContainer}>
        {isLoading && !displayUrl && (
          <View style={styles.loadingBox}>
            <Text style={styles.loadingText}>Loading image...</Text>
          </View>
        )}

        {isError && !displayUrl && (
          <View style={styles.loadingBox}>
            <Text style={styles.errorText}>Failed to load image</Text>
          </View>
        )}

        {displayUrl && (
          <ZoomableImage source={displayUrl} alt={candidate.title} />
        )}
      </View>

      {/* ── Metadata Card ── */}
      <View style={styles.metaCard}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.metaScroll}>
          <View style={styles.metaInner}>
            <Text style={styles.title}>{candidate.title}</Text>
            {candidate.artist && (
              <Text style={styles.artist}>{candidate.artist}</Text>
            )}
            {meta ? <Text style={styles.metaText}>{meta}</Text> : null}
            {candidate.source_api && (
              <Text style={styles.source}>{candidate.source_api}</Text>
            )}
          </View>
        </ScrollView>
        <TouchableOpacity
          style={styles.practiceBtn}
          activeOpacity={0.85}
          onPress={() => router.push({ pathname: '/practice/[id]', params: { id: candidate.id } })}
        >
          <Text style={styles.practiceBtnText}>Practice →</Text>
        </TouchableOpacity>
      </View>

      {/* ── Similar Artworks ── */}
      {(relatedCandidates.length > 0 || similarLoading) && (
        <View style={styles.similarSection}>
          <Text style={styles.similarLabel}>Similar artworks</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.similarScroll}>
            {(similarLoading && relatedCandidates.length === 0
              ? Array.from({ length: 4 })
              : relatedCandidates
            ).map((c, i) => {
              if (!c) {
                return <View key={i} style={[styles.similarCard, styles.similarCardSkeleton]} />
              }
              const item = c as ArtworkCandidate
              return (
                <TouchableOpacity
                  key={item.id}
                  style={styles.similarCard}
                  onPress={() => {
                    queryClient.setQueryData(['candidate', item.id], item)
                    router.push({ pathname: '/artwork/[id]', params: { id: item.id } })
                  }}
                  activeOpacity={0.8}
                >
                  {item.thumbnail_url
                    ? <Image source={{ uri: item.thumbnail_url }} style={styles.similarThumb} />
                    : <View style={[styles.similarThumb, styles.similarThumbFallback]}>
                        <Text style={styles.similarThumbText}>{item.title?.[0] ?? '?'}</Text>
                      </View>
                  }
                  <Text style={styles.similarTitle} numberOfLines={2}>{item.title}</Text>
                </TouchableOpacity>
              )
            })}
          </ScrollView>
        </View>
      )}
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#111',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingBottom: 10,
    paddingHorizontal: 16,
    backgroundColor: '#111',
    gap: 12,
  },
  backBtn: {
    paddingVertical: 4,
  },
  backText: {
    color: '#e5e5e3',
    fontSize: 15,
  },
  headerTitle: {
    flex: 1,
    color: '#ffffff',
    fontSize: 15,
    fontWeight: '600',
    textAlign: 'center',
  },
  headerSpacer: {
    width: 44,
  },
  imageContainer: {
    flex: 1,
    backgroundColor: '#111',
    position: 'relative',
  },
  loadingBox: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  loadingText: {
    color: '#999',
    fontSize: 14,
  },
  errorText: {
    color: '#dc2626',
    fontSize: 14,
  },
  metaCard: {
    backgroundColor: colors.surface,
    paddingVertical: 14,
    paddingHorizontal: 16,
    borderTopWidth: 1,
    borderColor: colors.border,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  metaScroll: {
    flex: 1,
  },
  metaInner: {
    gap: 2,
  },
  title: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.textPrimary,
  },
  artist: {
    fontSize: 14,
    color: colors.textSecondary,
  },
  metaText: {
    fontSize: 12,
    color: colors.textMuted,
  },
  source: {
    fontSize: 11,
    color: colors.textMuted,
  },
  practiceBtn: {
    backgroundColor: colors.accent,
    borderRadius: 8,
    paddingHorizontal: 16,
    paddingVertical: 9,
    flexShrink: 0,
  },
  practiceBtnText: {
    color: colors.surface,
    fontSize: 14,
    fontWeight: '600',
  },
  similarSection: {
    backgroundColor: colors.bg,
    borderTopWidth: 1,
    borderColor: colors.border,
    paddingTop: 10,
    paddingBottom: 10,
  },
  similarLabel: {
    fontSize: 11,
    color: colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    paddingHorizontal: 16,
    marginBottom: 8,
  },
  similarScroll: {
    paddingHorizontal: 12,
    gap: 10,
  },
  similarCard: {
    width: 80,
    gap: 4,
  },
  similarCardSkeleton: {
    height: 80,
    backgroundColor: colors.skeleton,
    borderRadius: 6,
  },
  similarThumb: {
    width: 80,
    height: 80,
    borderRadius: 6,
    backgroundColor: colors.placeholder,
  },
  similarThumbFallback: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  similarThumbText: {
    fontSize: 22,
    color: colors.textMuted,
    fontWeight: '700',
  },
  similarTitle: {
    fontSize: 10,
    color: colors.textSecondary,
    lineHeight: 13,
  },
})
