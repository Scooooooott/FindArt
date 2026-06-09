import { useState, useRef, useEffect } from 'react'
import { useLocalSearchParams, router } from 'expo-router'
import {
  View, Text, TouchableOpacity, StyleSheet, Alert,
  Platform, ActivityIndicator, ScrollView,
} from 'react-native'
import { StatusBar } from 'expo-status-bar'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useQueryClient } from '@tanstack/react-query'
import { useArtwork } from '../../hooks/useArtwork'
import { useLineart } from '../../hooks/useLineart'
import { ZoomableImage } from '../../components/ZoomableImage'
import type { ArtworkCandidate } from '../../types/api'

const _EMPTY_CANDIDATE: ArtworkCandidate = {
  id: '', source_api: '', title: '', artist: null, year: null, medium: null,
  thumbnail_url: null, image_url: null, iiif_base_url: null, source_url: null,
  detail_url: null, wikidata_id: null, is_public_domain: null, license_status: null,
  image_available: null, score: 0, matched_sources: [], metadata: {},
}

// ---------------------------------------------------------------------------
// Eyedropper helpers — web only
// ---------------------------------------------------------------------------
function initPickerCanvas(url: string): Promise<HTMLCanvasElement> {
  return new Promise((resolve, reject) => {
    const img = document.createElement('img') as HTMLImageElement
    img.crossOrigin = 'anonymous'
    img.onload = () => {
      try {
        const MAX = 1200
        const scale = Math.min(1, MAX / Math.max(img.naturalWidth || 1, img.naturalHeight || 1))
        const w = Math.round(img.naturalWidth * scale)
        const h = Math.round(img.naturalHeight * scale)
        const canvas = document.createElement('canvas')
        canvas.width = w
        canvas.height = h
        canvas.getContext('2d')!.drawImage(img, 0, 0, w, h)
        resolve(canvas)
      } catch (err) { reject(err) }
    }
    img.onerror = () => reject(new Error('load failed'))
    img.src = url
  })
}

function sampleColor(canvas: HTMLCanvasElement, relX: number, relY: number): string {
  const x = Math.max(0, Math.min(canvas.width - 1, Math.floor(relX * canvas.width)))
  const y = Math.max(0, Math.min(canvas.height - 1, Math.floor(relY * canvas.height)))
  const d = canvas.getContext('2d')!.getImageData(x, y, 1, 1).data
  return `#${d[0].toString(16).padStart(2, '0')}${d[1].toString(16).padStart(2, '0')}${d[2].toString(16).padStart(2, '0')}`
}

// ---------------------------------------------------------------------------
// Main screen
// ---------------------------------------------------------------------------
type GridDivisions = 0 | 3 | 4 | 6
type LineartMode = 'off' | 'canny' | 'fine'

export default function PracticeScreen() {
  const params = useLocalSearchParams<{ id: string }>()
  const insets = useSafeAreaInsets()
  const queryClient = useQueryClient()
  const candidate: ArtworkCandidate =
    queryClient.getQueryData<ArtworkCandidate>(['candidate', params.id])
    ?? _EMPTY_CANDIDATE
  const { data: artwork } = useArtwork(candidate)

  const iiifMediumUrl = candidate.iiif_base_url
    ? `${candidate.iiif_base_url}/full/1200,/0/default.jpg`
    : null
  const sourceUrl = artwork?.medium_url ?? iiifMediumUrl ?? candidate.image_url ?? candidate.thumbnail_url

  // ── Lineart mode ─────────────────────────────────────────────────────────
  const [lineartMode, setLineartMode] = useState<LineartMode>('off')
  const cycleLineart = () =>
    setLineartMode(m => m === 'off' ? 'canny' : m === 'canny' ? 'fine' : 'off')
  const { data: lineartDataUrl, isLoading: lineartLoading } = useLineart(
    lineartMode !== 'off' ? sourceUrl ?? null : null,
    lineartMode !== 'off' ? lineartMode : 'fine',
  )
  const displayUrl = lineartMode !== 'off' ? (lineartDataUrl ?? null) : sourceUrl

  // ── Grid ─────────────────────────────────────────────────────────────────
  const [gridDivisions, setGridDivisions] = useState<GridDivisions>(0)

  // ── Eyedropper ───────────────────────────────────────────────────────────
  const [pickerActive, setPickerActive] = useState(false)
  const [pickerLoading, setPickerLoading] = useState(false)
  const [pickerError, setPickerError] = useState<string | null>(null)
  const [pickerColor, setPickerColor] = useState<string | null>(null)
  const [pickerPos, setPickerPos] = useState<{ x: number; y: number } | null>(null)
  const [pickedColors, setPickedColors] = useState<string[]>([])
  const pickerCanvasRef = useRef<{ url: string; canvas: HTMLCanvasElement } | null>(null)

  // ── Magnifier ─────────────────────────────────────────────────────────────
  const [magnifierActive, setMagnifierActive] = useState(false)
  const [zoomLevel, setZoomLevel] = useState(4)
  const [magnifierPos, setMagnifierPos] = useState<{
    x: number; y: number; bgW: number; bgH: number; bgX: number; bgY: number
  } | null>(null)

  // ── Fullscreen ────────────────────────────────────────────────────────────
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [headerVisible, setHeaderVisible] = useState(true)
  const [toolbarVisible, setToolbarVisible] = useState(true)
  const headerHideTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const toolbarHideTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── Refs ──────────────────────────────────────────────────────────────────
  const canvasRef = useRef<View>(null)
  const imgRef = useRef<any>(null)

  // ── Effects ───────────────────────────────────────────────────────────────
  useEffect(() => {
    if (Platform.OS !== 'web') return
    const sync = () => setIsFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', sync)
    return () => document.removeEventListener('fullscreenchange', sync)
  }, [])

  useEffect(() => {
    if (Platform.OS !== 'web') return
    if (!isFullscreen) {
      setHeaderVisible(true)
      setToolbarVisible(true)
      return
    }
    setHeaderVisible(false)
    setToolbarVisible(false)

    const onMove = (e: MouseEvent) => {
      if (e.clientY < 60) {
        setHeaderVisible(true)
        if (headerHideTimer.current) clearTimeout(headerHideTimer.current)
        headerHideTimer.current = setTimeout(() => setHeaderVisible(false), 1500)
      }
      if (e.clientY > window.innerHeight - 60) {
        setToolbarVisible(true)
        if (toolbarHideTimer.current) clearTimeout(toolbarHideTimer.current)
        toolbarHideTimer.current = setTimeout(() => setToolbarVisible(false), 1500)
      }
    }
    document.addEventListener('mousemove', onMove)
    return () => {
      document.removeEventListener('mousemove', onMove)
      if (headerHideTimer.current) clearTimeout(headerHideTimer.current)
      if (toolbarHideTimer.current) clearTimeout(toolbarHideTimer.current)
    }
  }, [isFullscreen])

  // ── Derived fullscreen overlay styles (web only) ───────────────────────────
  const isWebFS = Platform.OS === 'web' && isFullscreen

  const headerFsStyle: any = isWebFS ? {
    position: 'absolute',
    top: 0, left: 0, right: 0,
    zIndex: 100,
    paddingTop: 12,
    opacity: headerVisible ? 1 : 0,
    transitionProperty: 'opacity',
    transitionDuration: '200ms',
    pointerEvents: headerVisible ? 'auto' : 'none',
  } : undefined

  const toolbarFsStyle: any = isWebFS ? {
    position: 'absolute',
    bottom: 0, left: 0, right: 0,
    zIndex: 100,
    opacity: toolbarVisible ? 1 : 0,
    transitionProperty: 'opacity',
    transitionDuration: '200ms',
    pointerEvents: toolbarVisible ? 'auto' : 'none',
  } : undefined

  // ── Handlers ──────────────────────────────────────────────────────────────
  const cycleGrid = () =>
    setGridDivisions(d => (d === 0 ? 3 : d === 3 ? 4 : d === 4 ? 6 : 0))

  const copyColor = async (hex: string) => {
    if (Platform.OS === 'web') {
      try { await navigator.clipboard.writeText(hex) } catch { window.alert(hex) }
    } else {
      Alert.alert('Color', hex)
    }
  }

  const togglePicker = async () => {
    if (Platform.OS !== 'web' || pickerLoading) return
    if (pickerActive) {
      setPickerActive(false)
      setPickerColor(null)
      setPickerPos(null)
      return
    }
    if (magnifierActive) { setMagnifierActive(false); setMagnifierPos(null) }
    setPickerActive(true)
    if (!sourceUrl || pickerCanvasRef.current?.url === sourceUrl) return
    pickerCanvasRef.current = null
    setPickerLoading(true)
    setPickerError(null)
    try {
      const canvas = await initPickerCanvas(sourceUrl)
      pickerCanvasRef.current = { url: sourceUrl, canvas }
    } catch {
      setPickerError('Color picking unavailable (CORS restriction)')
    } finally {
      setPickerLoading(false)
    }
  }

  const handleCanvasClick = (e: any) => {
    if (!pickerActive || !pickerColor || Platform.OS !== 'web') return
    const imgEl = imgRef.current
    if (!imgEl) return
    const r = imgEl.getBoundingClientRect()
    const cx = e.nativeEvent?.clientX ?? e.clientX
    const cy = e.nativeEvent?.clientY ?? e.clientY
    if (cx < r.left || cx > r.right || cy < r.top || cy > r.bottom) return
    const picked = pickerColor
    setPickedColors(prev => [picked, ...prev.filter(c => c !== picked)].slice(0, 8))
    copyColor(picked)
  }

  const toggleMagnifier = () => {
    if (pickerActive) { setPickerActive(false); setPickerColor(null); setPickerPos(null) }
    setMagnifierActive(m => !m)
    setMagnifierPos(null)
  }

  const handleCanvasMouseMove = (e: any) => {
    const cx: number = e.nativeEvent.clientX
    const cy: number = e.nativeEvent.clientY
    const imgEl = imgRef.current
    if (!imgEl) return

    const imgRect = imgEl.getBoundingClientRect()
    const inBounds = cx >= imgRect.left && cx <= imgRect.right && cy >= imgRect.top && cy <= imgRect.bottom
    const canvasEl = canvasRef.current as unknown as HTMLElement
    const canvasRect = canvasEl.getBoundingClientRect()
    const lx = cx - canvasRect.left
    const ly = cy - canvasRect.top

    if (magnifierActive) {
      if (inBounds) {
        const half = 80
        const bgW = zoomLevel * imgRect.width
        const bgH = zoomLevel * imgRect.height
        const relX = (cx - imgRect.left) / imgRect.width
        const relY = (cy - imgRect.top) / imgRect.height
        setMagnifierPos({ x: lx, y: ly, bgW, bgH, bgX: -(relX * bgW - half), bgY: -(relY * bgH - half) })
      } else {
        setMagnifierPos(null)
      }
    }

    if (pickerActive && pickerCanvasRef.current) {
      if (inBounds) {
        const relX = (cx - imgRect.left) / imgRect.width
        const relY = (cy - imgRect.top) / imgRect.height
        try {
          setPickerColor(sampleColor(pickerCanvasRef.current.canvas, relX, relY))
          setPickerPos({ x: lx, y: ly })
        } catch {
          setPickerColor(null); setPickerPos(null)
        }
      } else {
        setPickerColor(null); setPickerPos(null)
      }
    }
  }

  const handleCanvasMouseLeave = () => {
    setMagnifierPos(null)
    setPickerColor(null)
    setPickerPos(null)
  }

  const toggleFullscreen = async () => {
    if (Platform.OS !== 'web') return
    try {
      if (!document.fullscreenElement) {
        await document.documentElement.requestFullscreen()
      } else {
        await document.exitFullscreen()
      }
    } catch { /* browser may deny in some contexts */ }
  }

  // ── Render ────────────────────────────────────────────────────────────────
  const showPickerStrip = pickerActive || pickedColors.length > 0

  return (
    <View style={styles.container}>
      <StatusBar style="light" />

      {/* ── Header ── */}
      <View style={[
        styles.header,
        { paddingTop: Platform.OS === 'web' ? 52 : insets.top + 12 },
        headerFsStyle,
      ]}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} activeOpacity={0.7}>
          <Text style={styles.backText}>← Exit</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle} numberOfLines={1}>{candidate.title}</Text>
        <View style={styles.headerRight}>
          {lineartMode !== 'off' && (
            <View style={styles.modeTag}>
              <Text style={styles.modeTagText}>{lineartMode === 'canny' ? 'Fast Lineart' : 'Fine Lineart'}</Text>
            </View>
          )}
          {Platform.OS === 'web' ? (
            <TouchableOpacity onPress={toggleFullscreen} style={styles.fsBtn} activeOpacity={0.7}>
              <Text style={styles.fsBtnText}>{isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}</Text>
            </TouchableOpacity>
          ) : (
            <View style={styles.headerSpacer} />
          )}
        </View>
      </View>

      {/* ── Canvas ── */}
      <View
        ref={canvasRef}
        style={[styles.canvas, Platform.OS === 'web' && pickerActive ? { cursor: 'crosshair' } as any : undefined]}
        // @ts-ignore
        onMouseMove={(magnifierActive || pickerActive) && Platform.OS === 'web' ? handleCanvasMouseMove : undefined}
        // @ts-ignore
        onMouseLeave={Platform.OS === 'web' ? handleCanvasMouseLeave : undefined}
        // @ts-ignore
        onClick={pickerActive && Platform.OS === 'web' ? handleCanvasClick : undefined}
      >
        {/* Loading / unavailable */}
        {(lineartLoading || (!displayUrl && !lineartLoading)) && (
          <View style={styles.placeholder}>
            {lineartLoading
              ? <><ActivityIndicator size="large" color="#aaa" /><Text style={styles.loadingText}>{lineartMode === 'canny' ? 'Generating (3–5s)...' : 'Generating (15–30s)...'}</Text></>
              : <Text style={styles.placeholderText}>Image unavailable</Text>
            }
          </View>
        )}

        {/* ZoomableImage — handles Web (react-zoom-pan-pinch) and Android (gesture-handler) */}
        {!lineartLoading && displayUrl && (
          <ZoomableImage
            source={displayUrl}
            alt={candidate.title}
            gridDivisions={gridDivisions}
            imgRef={imgRef}
            isFullscreen={isWebFS}
          />
        )}

        {/* Magnifier lens — web only */}
        {magnifierActive && magnifierPos && displayUrl && Platform.OS === 'web' && (
          <>
            <div style={{
              position: 'absolute',
              left: magnifierPos.x - 80, top: magnifierPos.y - 80,
              width: 160, height: 160,
              borderRadius: '50%',
              border: '2px solid rgba(255,255,255,0.5)',
              pointerEvents: 'none',
              backgroundImage: `url(${displayUrl})`,
              backgroundSize: `${magnifierPos.bgW}px ${magnifierPos.bgH}px`,
              backgroundPosition: `${magnifierPos.bgX}px ${magnifierPos.bgY}px`,
              backgroundRepeat: 'no-repeat',
              boxShadow: '0 2px 12px rgba(0,0,0,0.6)',
              zIndex: 20,
            } as any} />
            <div style={{
              position: 'absolute',
              left: magnifierPos.x,
              top: magnifierPos.y - 102,
              transform: 'translateX(-50%)',
              backgroundColor: 'rgba(0,0,0,0.65)',
              color: '#fff',
              fontSize: 11,
              padding: '2px 8px',
              borderRadius: 10,
              pointerEvents: 'none',
              zIndex: 21,
              whiteSpace: 'nowrap',
            } as any}>
              {zoomLevel}×
            </div>
          </>
        )}

        {/* Magnifier zoom slider — web only */}
        {magnifierActive && Platform.OS === 'web' && (
          <div style={{
            position: 'absolute',
            bottom: 52, right: 12,
            backgroundColor: 'rgba(0,0,0,0.72)',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: 10,
            padding: '8px 14px',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            zIndex: 30,
            userSelect: 'none',
          } as any}>
            <span style={{ color: '#aaa', fontSize: 11, whiteSpace: 'nowrap' }}>Zoom</span>
            <input
              type="range"
              min={2}
              max={10}
              step={1}
              value={zoomLevel}
              onChange={(e: any) => setZoomLevel(Number(e.target.value))}
              style={{ width: 100, accentColor: '#d4c97a', cursor: 'pointer' }}
            />
            <span style={{ color: '#fff', fontSize: 13, fontWeight: 'bold', minWidth: 28, textAlign: 'right' }}>{zoomLevel}×</span>
          </div>
        )}

        {/* Eyedropper color tooltip — web only */}
        {pickerActive && pickerPos && pickerColor && Platform.OS === 'web' && (
          <div style={{
            position: 'absolute',
            left: pickerPos.x + 14, top: pickerPos.y - 14,
            display: 'flex', alignItems: 'center', gap: 6,
            backgroundColor: 'rgba(0,0,0,0.82)',
            border: '1px solid rgba(255,255,255,0.15)',
            borderRadius: 6, padding: '4px 8px',
            pointerEvents: 'none', zIndex: 20,
          } as any}>
            <div style={{
              width: 18, height: 18,
              backgroundColor: pickerColor,
              borderRadius: 3,
              border: '1px solid rgba(255,255,255,0.3)',
              flexShrink: 0,
            } as any} />
            <span style={{ color: '#fff', fontSize: 11, fontFamily: 'monospace' }}>{pickerColor}</span>
          </div>
        )}
      </View>

      {/* ── Picked colors strip (hidden in fullscreen) ── */}
      {showPickerStrip && !isWebFS && (
        <View style={styles.pickerStrip}>
          {pickerLoading ? (
            <View style={styles.stripRow}>
              <ActivityIndicator color="#aaa" size="small" />
              <Text style={styles.stripHint}>Loading image...</Text>
            </View>
          ) : pickerError ? (
            <Text style={styles.stripError}>{pickerError}</Text>
          ) : pickedColors.length > 0 ? (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.paletteScroll}>
              {pickedColors.map((hex, i) => (
                <TouchableOpacity key={i} style={styles.paletteChip} onPress={() => copyColor(hex)} activeOpacity={0.75}>
                  <View style={[styles.paletteColor, { backgroundColor: hex }]} />
                  <Text style={styles.paletteHex}>{hex}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
          ) : (
            <Text style={styles.stripHint}>Click on the image to pick a color</Text>
          )}
        </View>
      )}

      {/* ── Toolbar ── */}
      <View style={[styles.toolbar, toolbarFsStyle]}>

        {/* Lineart */}
        <TouchableOpacity
          style={[styles.toolBtn, lineartMode !== 'off' && styles.toolBtnActive]}
          onPress={cycleLineart}
          disabled={lineartLoading}
          activeOpacity={0.7}
        >
          {lineartLoading
            ? <ActivityIndicator size="small" color="#aaa" />
            : <Text style={[styles.toolLabel, lineartMode !== 'off' && styles.toolLabelActive]}>Lineart</Text>
          }
          <Text style={styles.toolSub}>
            {lineartMode === 'off'
              ? 'Tap to generate'
              : lineartLoading
              ? 'Generating...'
              : lineartMode === 'canny' ? 'Fast · tap for Fine' : 'Fine · tap to disable'
            }
          </Text>
        </TouchableOpacity>

        {/* Grid */}
        <TouchableOpacity
          style={[styles.toolBtn, gridDivisions > 0 && styles.toolBtnActive]}
          onPress={cycleGrid}
          activeOpacity={0.7}
        >
          <Text style={[styles.toolLabel, gridDivisions > 0 && styles.toolLabelActive]}>Grid</Text>
          <Text style={styles.toolSub}>{gridDivisions === 0 ? 'Off' : `${gridDivisions}×${gridDivisions}`}</Text>
        </TouchableOpacity>

        {/* Eyedropper */}
        <TouchableOpacity
          style={[styles.toolBtn, pickerActive && styles.toolBtnActive]}
          onPress={Platform.OS === 'web' ? togglePicker : undefined}
          disabled={pickerLoading}
          activeOpacity={0.7}
        >
          {pickerLoading
            ? <ActivityIndicator size="small" color="#aaa" />
            : <Text style={[styles.toolLabel, pickerActive && styles.toolLabelActive]}>Eyedropper</Text>
          }
          <Text style={styles.toolSub}>
            {Platform.OS !== 'web' ? 'Web only' : pickerActive ? 'Tap to disable' : 'Tap to enable'}
          </Text>
        </TouchableOpacity>

        {/* Magnifier */}
        <TouchableOpacity
          style={[styles.toolBtn, magnifierActive && styles.toolBtnActive]}
          onPress={Platform.OS === 'web' ? toggleMagnifier : undefined}
          activeOpacity={0.7}
        >
          <Text style={[styles.toolLabel, magnifierActive && styles.toolLabelActive]}>Magnifier</Text>
          <Text style={styles.toolSub}>
            {Platform.OS !== 'web'
              ? 'Web only'
              : magnifierActive ? `${zoomLevel}× · adjust` : 'Hover to zoom'
            }
          </Text>
        </TouchableOpacity>

        {/* TODO: Compare mode — upload a photo of your work alongside the original.
            expo-image-picker to select user's painting photo, display side-by-side
            or as a toggle with the original for progress comparison. */}

      </View>
    </View>
  )
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------
const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0a0a0a' },

  header: {
    flexDirection: 'row', alignItems: 'center',
    paddingBottom: 10, paddingHorizontal: 16,
    backgroundColor: '#111', gap: 12,
  },
  backBtn: { paddingVertical: 4 },
  backText: { color: '#e5e5e3', fontSize: 15 },
  headerTitle: { flex: 1, color: '#fff', fontSize: 15, fontWeight: '600', textAlign: 'center' },
  headerSpacer: { width: 44 },
  headerRight: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  modeTag: { backgroundColor: '#3a3a2a', borderRadius: 6, paddingHorizontal: 8, paddingVertical: 3 },
  modeTagText: { color: '#d4c97a', fontSize: 12, fontWeight: '600' },
  fsBtn: { paddingHorizontal: 8, paddingVertical: 4, backgroundColor: '#2a2a2a', borderRadius: 6 },
  fsBtnText: { color: '#aaa', fontSize: 12 },

  canvas: { flex: 1, backgroundColor: '#0a0a0a', position: 'relative' },
  placeholder: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12 },
  placeholderText: { color: '#555', fontSize: 14 },
  loadingText: { color: '#888', fontSize: 13 },

  pickerStrip: {
    backgroundColor: '#141414',
    borderTopWidth: 1, borderColor: '#2a2a2a',
    paddingVertical: 10, minHeight: 72,
    justifyContent: 'center',
  },
  stripRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 },
  stripHint: { color: '#555', fontSize: 13, textAlign: 'center' },
  stripError: { color: '#666', fontSize: 13, textAlign: 'center', padding: 16 },
  paletteScroll: { paddingHorizontal: 12, gap: 8 },
  paletteChip: { alignItems: 'center', gap: 4 },
  paletteColor: { width: 40, height: 40, borderRadius: 6, borderWidth: 1, borderColor: 'rgba(255,255,255,0.1)' },
  paletteHex: { color: '#aaa', fontSize: 9, fontFamily: 'monospace' },

  toolbar: {
    flexDirection: 'row',
    backgroundColor: '#1a1a1a', borderTopWidth: 1, borderColor: '#2a2a2a',
    paddingVertical: 12, paddingHorizontal: 8, gap: 8,
  },
  toolBtn: {
    flex: 1, alignItems: 'center', paddingVertical: 8,
    borderRadius: 8, backgroundColor: '#242424', gap: 3,
  },
  toolBtnActive: { backgroundColor: '#2a2a1a', borderWidth: 1, borderColor: '#d4c97a' },
  toolLabel: { color: '#e5e5e3', fontSize: 14, fontWeight: '600' },
  toolLabelActive: { color: '#d4c97a' },
  toolSub: { color: '#555', fontSize: 10 },
})
