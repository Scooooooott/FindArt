import { useLocalSearchParams, router } from 'expo-router'
import { View, Text, TouchableOpacity, StyleSheet, ScrollView, Platform } from 'react-native'
import { Image } from 'expo-image'
import { TransformWrapper, TransformComponent } from 'react-zoom-pan-pinch'
import { useArtwork } from '../../hooks/useArtwork'
import { colors } from '../../constants/colors'
import type { ArtworkCandidate } from '../../types/api'

export default function ArtworkScreen() {
  const params = useLocalSearchParams<{ id: string; data: string }>()
  const candidate: ArtworkCandidate = JSON.parse(params.data ?? '{}')
  const { data: artwork, isLoading, isError } = useArtwork(candidate)

  // Prefer resolved medium_url, fall back to candidate's own URLs
  const displayUrl = artwork?.medium_url ?? candidate.image_url ?? candidate.thumbnail_url

  const meta = [candidate.year, candidate.medium]
    .filter(Boolean)
    .join(' · ')

  return (
    <View style={styles.container}>
      {/* ── Header ── */}
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} activeOpacity={0.7}>
          <Text style={styles.backText}>← 返回</Text>
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
            <Text style={styles.loadingText}>加载图片中...</Text>
          </View>
        )}

        {isError && !displayUrl && (
          <View style={styles.loadingBox}>
            <Text style={styles.errorText}>图片加载失败</Text>
          </View>
        )}

        {displayUrl && Platform.OS === 'web' && (
          <TransformWrapper
            initialScale={1}
            minScale={0.3}
            maxScale={10}
            centerOnInit
            doubleClick={{ mode: 'reset' }}
          >
            {({ resetTransform }) => (
              <>
                <TransformComponent
                  wrapperStyle={{ width: '100%', height: '100%' } as any}
                  contentStyle={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' } as any}
                >
                  <img
                    src={displayUrl}
                    alt={candidate.title}
                    style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain', userSelect: 'none' }}
                    draggable={false}
                  />
                </TransformComponent>
                <TouchableOpacity style={styles.resetBtn} onPress={() => resetTransform()} activeOpacity={0.8}>
                  <Text style={styles.resetText}>复位</Text>
                </TouchableOpacity>
              </>
            )}
          </TransformWrapper>
        )}

        {displayUrl && Platform.OS !== 'web' && (
          // TODO: Replace with gesture-based zoom for mobile (see docs/frontend_todo.md)
          <Image
            source={{ uri: displayUrl }}
            style={styles.nativeImage}
            contentFit="contain"
          />
        )}
      </View>

      {/* ── Metadata Card ── */}
      <View style={styles.metaCard}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false}>
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
          onPress={() => router.push({ pathname: '/practice/[id]', params: { id: candidate.id, data: params.data } })}
        >
          <Text style={styles.practiceBtnText}>开始临摹 →</Text>
        </TouchableOpacity>
      </View>
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
    paddingTop: 52,
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
  nativeImage: {
    flex: 1,
  },
  resetBtn: {
    position: 'absolute',
    bottom: 12,
    right: 12,
    backgroundColor: 'rgba(0,0,0,0.5)',
    borderRadius: 6,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  resetText: {
    color: '#fff',
    fontSize: 12,
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
    marginLeft: 'auto',
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
})
