import { useState } from 'react'
import { View, TextInput, TouchableOpacity, Text, StyleSheet, ActivityIndicator, Platform } from 'react-native'
import { colors } from '../constants/colors'

interface Props {
  readonly onSearch: (text: string) => void
  readonly loading?: boolean
}

export function SearchBar({ onSearch, loading }: Props) {
  const [text, setText] = useState('')

  const submit = () => {
    const trimmed = text.trim()
    if (trimmed) onSearch(trimmed)
  }

  return (
    <View style={styles.row}>
      <TextInput
        style={styles.input}
        value={text}
        onChangeText={setText}
        placeholder="Describe a painting, e.g. melting clocks by Dalí"
        placeholderTextColor={colors.textMuted}
        onSubmitEditing={submit}
        returnKeyType="search"
        editable={!loading}
      />
      <TouchableOpacity style={styles.button} onPress={submit} disabled={loading} activeOpacity={0.8}>
        {loading
          ? <ActivityIndicator size="small" color={colors.surface} />
          : <Text style={styles.buttonText}>Search</Text>
        }
      </TouchableOpacity>
    </View>
  )
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    gap: 8,
  },
  input: {
    flex: 1,
    height: 44,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingHorizontal: 14,
    fontSize: 15,
    color: colors.textPrimary,
    backgroundColor: colors.surface,
    ...(Platform.OS === 'web' ? { outlineStyle: 'none' } : {}),
  } as any,
  button: {
    height: 44,
    paddingHorizontal: 18,
    backgroundColor: colors.accent,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    minWidth: 72,
  },
  buttonText: {
    color: colors.surface,
    fontSize: 15,
    fontWeight: '600',
  },
})
