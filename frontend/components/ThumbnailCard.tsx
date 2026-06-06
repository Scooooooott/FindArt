import { View, Text, TouchableOpacity, StyleSheet } from 'react-native'
import { Image } from 'expo-image'
import { colors } from '../constants/colors'
import type { ArtworkCandidate } from '../types/api'

interface Props {
  readonly candidate: ArtworkCandidate
  readonly onPress: () => void
  readonly isFavourited?: boolean
  readonly onToggleFavourite?: () => void
}

export function ThumbnailCard({ candidate, onPress, isFavourited, onToggleFavourite }: Props) {
  const hasImage = !!candidate.thumbnail_url

  return (
    <TouchableOpacity style={styles.card} onPress={onPress} activeOpacity={0.85}>
      <View style={styles.imageWrap}>
        {hasImage ? (
          <Image
            source={{ uri: candidate.thumbnail_url! }}
            style={styles.image}
            contentFit="cover"
            transition={150}
          />
        ) : (
          <View style={[styles.image, styles.placeholder]}>
            <Text style={styles.placeholderIcon}>🖼</Text>
          </View>
        )}

        {/* Source badge — bottom-left */}
        <View style={styles.sourceBadge}>
          <Text style={styles.sourceBadgeText}>{candidate.source_api}</Text>
        </View>

        {/* Favourite button — top-right */}
        {onToggleFavourite && (
          <TouchableOpacity
            style={styles.heartBtn}
            onPress={onToggleFavourite}
            hitSlop={{ top: 6, right: 6, bottom: 6, left: 6 }}
            activeOpacity={0.7}
          >
            <Text style={[styles.heartIcon, isFavourited && styles.heartActive]}>
              {isFavourited ? '♥' : '♡'}
            </Text>
          </TouchableOpacity>
        )}
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
  heartBtn: {
    position: 'absolute',
    top: 5,
    right: 5,
    backgroundColor: 'rgba(0,0,0,0.45)',
    borderRadius: 14,
    width: 28,
    height: 28,
    alignItems: 'center',
    justifyContent: 'center',
  },
  heartIcon: {
    fontSize: 15,
    color: 'rgba(255,255,255,0.85)',
    lineHeight: 17,
  },
  heartActive: {
    color: '#e85d75',
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
