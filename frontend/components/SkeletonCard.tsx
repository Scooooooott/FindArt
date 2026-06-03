import { View, StyleSheet } from 'react-native'
import { colors } from '../constants/colors'

interface Props {
  mode: 'grid' | 'list'
}

export function SkeletonCard({ mode }: Props) {
  if (mode === 'list') {
    return (
      <View style={list.row}>
        <View style={list.thumb} />
        <View style={list.lines}>
          <View style={[list.line, { width: '70%' }]} />
          <View style={[list.line, { width: '45%', marginTop: 6 }]} />
          <View style={[list.line, { width: '55%', marginTop: 4 }]} />
        </View>
      </View>
    )
  }

  return (
    <View style={grid.card}>
      <View style={grid.image} />
      <View style={grid.meta}>
        <View style={[grid.line, { width: '80%' }]} />
        <View style={[grid.line, { width: '55%', marginTop: 5 }]} />
      </View>
    </View>
  )
}

const grid = StyleSheet.create({
  card: {
    flex: 1,
    margin: 6,
    borderRadius: 10,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  image: {
    aspectRatio: 1,
    width: '100%',
    backgroundColor: colors.skeleton,
  },
  meta: {
    padding: 8,
  },
  line: {
    height: 10,
    borderRadius: 5,
    backgroundColor: colors.skeleton,
  },
})

const list = StyleSheet.create({
  row: {
    flexDirection: 'row',
    gap: 12,
    padding: 12,
    borderBottomWidth: 1,
    borderColor: colors.border,
  },
  thumb: {
    width: 72,
    height: 72,
    borderRadius: 6,
    backgroundColor: colors.skeleton,
    flexShrink: 0,
  },
  lines: {
    flex: 1,
    justifyContent: 'center',
  },
  line: {
    height: 10,
    borderRadius: 5,
    backgroundColor: colors.skeleton,
  },
})
