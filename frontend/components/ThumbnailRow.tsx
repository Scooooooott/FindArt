import { View, Text, TouchableOpacity, Image, StyleSheet } from 'react-native'
import { colors } from '../constants/colors'
import type { ArtworkCandidate } from '../types/api'

interface Props {
  candidate: ArtworkCandidate
  onPress: () => void
  isFavourited?: boolean
  onToggleFavourite?: () => void
}

export function ThumbnailRow({ candidate, onPress, isFavourited, onToggleFavourite }: Props) {
  const hasImage = !!candidate.thumbnail_url
  const meta = [candidate.year, candidate.medium, candidate.source_api]
    .filter(Boolean)
    .join(' · ')

  return (
    <TouchableOpacity style={styles.row} onPress={onPress} activeOpacity={0.85}>
      <View style={styles.thumbWrap}>
        {hasImage ? (
          <Image
            source={{ uri: candidate.thumbnail_url! }}
            style={styles.thumb}
            resizeMode="cover"
          />
        ) : (
          <View style={[styles.thumb, styles.placeholder]}>
            <Text style={styles.placeholderIcon}>🖼</Text>
          </View>
        )}
      </View>

      <View style={styles.info}>
        <Text style={styles.title} numberOfLines={2}>{candidate.title}</Text>
        {candidate.artist && (
          <Text style={styles.artist} numberOfLines={1}>{candidate.artist}</Text>
        )}
        {meta ? <Text style={styles.meta} numberOfLines={1}>{meta}</Text> : null}
      </View>

      {/* Favourite button — right edge */}
      {onToggleFavourite && (
        <TouchableOpacity
          style={styles.heartBtn}
          onPress={onToggleFavourite}
          hitSlop={{ top: 8, right: 8, bottom: 8, left: 8 }}
          activeOpacity={0.7}
        >
          <Text style={[styles.heartIcon, isFavourited && styles.heartActive]}>
            {isFavourited ? '♥' : '♡'}
          </Text>
        </TouchableOpacity>
      )}
    </TouchableOpacity>
  )
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    padding: 12,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderColor: colors.border,
  },
  thumbWrap: {
    width: 72,
    height: 72,
    borderRadius: 6,
    overflow: 'hidden',
    flexShrink: 0,
    backgroundColor: colors.skeleton,
  },
  thumb: {
    width: '100%',
    height: '100%',
  },
  placeholder: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  placeholderIcon: {
    fontSize: 24,
  },
  info: {
    flex: 1,
    justifyContent: 'center',
    gap: 3,
  },
  title: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.textPrimary,
    lineHeight: 20,
  },
  artist: {
    fontSize: 13,
    color: colors.textSecondary,
  },
  meta: {
    fontSize: 12,
    color: colors.textMuted,
  },
  heartBtn: {
    paddingHorizontal: 6,
    flexShrink: 0,
  },
  heartIcon: {
    fontSize: 20,
    color: colors.border,
  },
  heartActive: {
    color: '#e85d75',
  },
})
