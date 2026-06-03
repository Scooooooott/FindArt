import { View, Text, TouchableOpacity, Image, StyleSheet } from 'react-native'
import { colors } from '../constants/colors'
import type { ArtworkCandidate } from '../types/api'

interface Props {
  candidate: ArtworkCandidate
  onPress: () => void
}

export function ThumbnailCard({ candidate, onPress }: Props) {
  const hasImage = !!candidate.thumbnail_url

  return (
    <TouchableOpacity style={styles.card} onPress={onPress} activeOpacity={0.85}>
      <View style={styles.imageWrap}>
        {hasImage ? (
          <Image
            source={{ uri: candidate.thumbnail_url! }}
            style={styles.image}
            resizeMode="cover"
          />
        ) : (
          <View style={[styles.image, styles.placeholder]}>
            <Text style={styles.placeholderIcon}>🖼</Text>
          </View>
        )}
        <View style={styles.sourceBadge}>
          <Text style={styles.sourceBadgeText}>{candidate.source_api}</Text>
        </View>
      </View>
      <View style={styles.meta}>
        <Text style={styles.title} numberOfLines={2}>{candidate.title}</Text>
        {candidate.artist && (
          <Text style={styles.artist} numberOfLines={1}>{candidate.artist}</Text>
        )}
        {candidate.year && (
          <Text style={styles.year}>{candidate.year}</Text>
        )}
      </View>
    </TouchableOpacity>
  )
}

const styles = StyleSheet.create({
  card: {
    flex: 1,
    margin: 6,
    backgroundColor: colors.surface,
    borderRadius: 10,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: colors.border,
  },
  imageWrap: {
    aspectRatio: 1,
    width: '100%',
    backgroundColor: colors.skeleton,
  },
  image: {
    width: '100%',
    height: '100%',
  },
  placeholder: {
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.skeleton,
  },
  placeholderIcon: {
    fontSize: 32,
  },
  sourceBadge: {
    position: 'absolute',
    bottom: 4,
    left: 4,
    backgroundColor: 'rgba(0,0,0,0.6)',
    borderRadius: 4,
    paddingHorizontal: 5,
    paddingVertical: 2,
  },
  sourceBadgeText: {
    color: '#fff',
    fontSize: 9,
    fontWeight: '600',
    letterSpacing: 0.3,
  },
  meta: {
    padding: 8,
    gap: 2,
  },
  title: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textPrimary,
    lineHeight: 18,
  },
  artist: {
    fontSize: 12,
    color: colors.textSecondary,
  },
  year: {
    fontSize: 11,
    color: colors.textMuted,
  },
})
