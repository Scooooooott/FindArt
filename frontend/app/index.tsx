import { useState } from 'react'
import { View, Text, ScrollView, StyleSheet, TouchableOpacity, TextInput } from 'react-native'
import { router } from 'expo-router'
import { SearchBar } from '../components/SearchBar'
import { ViewToggle, type ViewMode } from '../components/ViewToggle'
import { ThumbnailCard } from '../components/ThumbnailCard'
import { ThumbnailRow } from '../components/ThumbnailRow'
import { SkeletonCard } from '../components/SkeletonCard'
import { useSearch } from '../hooks/useSearch'
import { colors } from '../constants/colors'
import type { ArtworkCandidate } from '../types/api'

const SKELETON_COUNT = 6
const MAX_CLARIFICATION_ROUNDS = 2

export default function SearchScreen() {
  const [query, setQuery] = useState('')
  const [viewMode, setViewMode] = useState<ViewMode>('grid')
  const [roundCount, setRoundCount] = useState(0)
  const [clarificationInput, setClarificationInput] = useState('')

  const { data, isLoading, isError, error } = useSearch(query)
  const candidates = data?.candidates ?? []
  const fallbackMode = data?.diagnostics?.fallback_mode ?? null
  const clarification = roundCount < MAX_CLARIFICATION_ROUNDS ? (data?.clarification ?? null) : null

  const handleSearch = (text: string) => {
    setQuery(text)
    setRoundCount(0)
    setClarificationInput('')
  }

  const handleClarify = () => {
    const answer = clarificationInput.trim()
    if (!answer) return
    setQuery(q => q + '，' + answer)
    setRoundCount(r => r + 1)
    setClarificationInput('')
  }

  const handleSelect = (candidate: ArtworkCandidate) => {
    router.push({
      pathname: '/artwork/[id]',
      params: { id: candidate.id, data: JSON.stringify(candidate) },
    })
  }

  return (
    <View style={styles.container}>
      {/* ── Header ── */}
      <View style={styles.header}>
        <Text style={styles.logo}>FindArt</Text>
        <Text style={styles.tagline}>描述一幅画，找到它的高清原图</Text>
        <SearchBar onSearch={handleSearch} loading={isLoading} />
      </View>

      {/* ── Toolbar ── */}
      {(candidates.length > 0 || isLoading) && (
        <View style={styles.toolbar}>
          <Text style={styles.resultCount}>
            {isLoading ? '搜索中...' : `${candidates.length} 件作品`}
          </Text>
          <ViewToggle mode={viewMode} onChange={setViewMode} />
        </View>
      )}

      {/* ── Results ── */}
      <ScrollView style={styles.scroll} contentContainerStyle={styles.scrollContent}>
        {isError && (
          <View style={styles.stateBox}>
            <Text style={styles.stateIcon}>⚠️</Text>
            <Text style={styles.stateTitle}>搜索失败</Text>
            <Text style={styles.stateMsg}>{error?.message}</Text>
            <TouchableOpacity style={styles.retryBtn} onPress={() => setQuery(q => q)}>
              <Text style={styles.retryText}>重试</Text>
            </TouchableOpacity>
          </View>
        )}

        {!isLoading && !isError && query.trim().length > 1 && candidates.length === 0 && (
          <View style={styles.stateBox}>
            <Text style={styles.stateIcon}>🔍</Text>
            <Text style={styles.stateTitle}>未找到匹配作品</Text>
            <Text style={styles.stateMsg}>换个描述方式试试，例如加上艺术家名字或作品年代</Text>
          </View>
        )}

        {!query && (
          <View style={styles.stateBox}>
            <Text style={styles.stateIcon}>🎨</Text>
            <Text style={styles.stateTitle}>在上方输入对画作的描述</Text>
            <Text style={styles.stateMsg}>支持中英文，可以描述画面内容、艺术家、年代或感受</Text>
          </View>
        )}

        {/* Fallback notice */}
        {fallbackMode && candidates.length > 0 && (
          <View style={styles.fallbackNotice}>
            <Text style={styles.fallbackText}>未找到精确匹配，以下为相关作品</Text>
          </View>
        )}

        {/* Grid view */}
        {viewMode === 'grid' && (
          <View style={styles.grid}>
            {isLoading
              ? Array.from({ length: SKELETON_COUNT }).map((_, i) => (
                  <SkeletonCard key={i} mode="grid" />
                ))
              : candidates.map(c => (
                  <ThumbnailCard key={c.id} candidate={c} onPress={() => handleSelect(c)} />
                ))}
          </View>
        )}

        {/* List view */}
        {viewMode === 'list' && (
          <View>
            {isLoading
              ? Array.from({ length: SKELETON_COUNT }).map((_, i) => (
                  <SkeletonCard key={i} mode="list" />
                ))
              : candidates.map(c => (
                  <ThumbnailRow key={c.id} candidate={c} onPress={() => handleSelect(c)} />
                ))}
          </View>
        )}

        {/* Clarification card */}
        {clarification && !isLoading && (
          <View style={styles.clarificationCard}>
            <Text style={styles.clarificationLabel}>描述更精确可以找到更好的结果</Text>
            <Text style={styles.clarificationQuestion}>{clarification.question}</Text>
            <View style={styles.clarificationRow}>
              <TextInput
                style={styles.clarificationInput}
                value={clarificationInput}
                onChangeText={setClarificationInput}
                placeholder="补充描述..."
                placeholderTextColor={colors.textMuted}
                onSubmitEditing={handleClarify}
                returnKeyType="search"
              />
              <TouchableOpacity
                style={[styles.clarificationBtn, !clarificationInput.trim() && styles.clarificationBtnDisabled]}
                onPress={handleClarify}
                disabled={!clarificationInput.trim()}
                activeOpacity={0.7}
              >
                <Text style={styles.clarificationBtnText}>确认</Text>
              </TouchableOpacity>
            </View>
            {roundCount > 0 && (
              <Text style={styles.clarificationRound}>第 {roundCount}/{MAX_CLARIFICATION_ROUNDS} 轮补充</Text>
            )}
          </View>
        )}
      </ScrollView>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bg,
  },
  header: {
    paddingHorizontal: 20,
    paddingTop: 56,
    paddingBottom: 16,
    gap: 6,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderColor: colors.border,
  },
  logo: {
    fontSize: 26,
    fontWeight: '700',
    color: colors.textPrimary,
    letterSpacing: -0.5,
  },
  tagline: {
    fontSize: 13,
    color: colors.textSecondary,
    marginBottom: 6,
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
  fallbackNotice: {
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  fallbackText: {
    fontSize: 12,
    color: colors.textMuted,
    fontStyle: 'italic',
  },
  clarificationCard: {
    marginHorizontal: 6,
    marginTop: 16,
    marginBottom: 8,
    padding: 14,
    backgroundColor: colors.surface,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 8,
  },
  clarificationLabel: {
    fontSize: 11,
    color: colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  clarificationQuestion: {
    fontSize: 14,
    color: colors.textPrimary,
    fontWeight: '500',
    lineHeight: 20,
  },
  clarificationRow: {
    flexDirection: 'row',
    gap: 8,
  },
  clarificationInput: {
    flex: 1,
    height: 40,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 7,
    paddingHorizontal: 12,
    fontSize: 14,
    color: colors.textPrimary,
    backgroundColor: colors.bg,
    outlineStyle: 'none',
  } as any,
  clarificationBtn: {
    height: 40,
    paddingHorizontal: 16,
    backgroundColor: colors.accent,
    borderRadius: 7,
    alignItems: 'center',
    justifyContent: 'center',
  },
  clarificationBtnDisabled: {
    opacity: 0.4,
  },
  clarificationBtnText: {
    color: colors.surface,
    fontSize: 14,
    fontWeight: '600',
  },
  clarificationRound: {
    fontSize: 11,
    color: colors.textMuted,
    textAlign: 'right',
  },
  stateBox: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 40,
    gap: 8,
  },
  stateIcon: {
    fontSize: 40,
    marginBottom: 8,
  },
  stateTitle: {
    fontSize: 17,
    fontWeight: '600',
    color: colors.textPrimary,
    textAlign: 'center',
  },
  stateMsg: {
    fontSize: 14,
    color: colors.textSecondary,
    textAlign: 'center',
    lineHeight: 20,
  },
  retryBtn: {
    marginTop: 12,
    paddingHorizontal: 20,
    paddingVertical: 8,
    backgroundColor: colors.accent,
    borderRadius: 7,
  },
  retryText: {
    color: colors.surface,
    fontSize: 14,
    fontWeight: '600',
  },
})
