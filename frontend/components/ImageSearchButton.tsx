import { TouchableOpacity, Text, StyleSheet, ActivityIndicator } from 'react-native'
import { colors } from '../constants/colors'

interface Props {
  onPress: () => void
  loading?: boolean
  active?: boolean
}

export function ImageSearchButton({ onPress, loading = false, active = false }: Props) {
  return (
    <TouchableOpacity
      style={[styles.btn, active && styles.btnActive]}
      onPress={onPress}
      disabled={loading}
      activeOpacity={0.75}
      hitSlop={{ top: 8, right: 8, bottom: 8, left: 8 }}
    >
      {loading
        ? <ActivityIndicator size="small" color={active ? colors.surface : colors.textSecondary} />
        : <Text style={styles.icon}>🖼</Text>
      }
    </TouchableOpacity>
  )
}

const styles = StyleSheet.create({
  btn: {
    width: 40,
    height: 40,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.bg,
  },
  btnActive: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  icon: {
    fontSize: 18,
  },
})
