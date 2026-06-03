import { View, TouchableOpacity, Text, StyleSheet } from 'react-native'
import { colors } from '../constants/colors'

export type ViewMode = 'grid' | 'list'

interface Props {
  mode: ViewMode
  onChange: (mode: ViewMode) => void
}

export function ViewToggle({ mode, onChange }: Props) {
  return (
    <View style={styles.container}>
      <TouchableOpacity
        style={[styles.btn, mode === 'grid' && styles.active]}
        onPress={() => onChange('grid')}
        activeOpacity={0.7}
      >
        <Text style={[styles.icon, mode === 'grid' && styles.activeIcon]}>⊞</Text>
      </TouchableOpacity>
      <TouchableOpacity
        style={[styles.btn, mode === 'list' && styles.active]}
        onPress={() => onChange('list')}
        activeOpacity={0.7}
      >
        <Text style={[styles.icon, mode === 'list' && styles.activeIcon]}>☰</Text>
      </TouchableOpacity>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 7,
    overflow: 'hidden',
  },
  btn: {
    width: 36,
    height: 32,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.surface,
  },
  active: {
    backgroundColor: colors.accent,
  },
  icon: {
    fontSize: 16,
    color: colors.textSecondary,
  },
  activeIcon: {
    color: colors.surface,
  },
})
