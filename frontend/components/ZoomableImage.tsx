import React from 'react'
import { View, TouchableOpacity, Text, StyleSheet } from 'react-native'
import { TransformWrapper, TransformComponent } from 'react-zoom-pan-pinch'

interface Props {
  source: string
  alt?: string
  gridDivisions?: number
  imgRef?: React.MutableRefObject<HTMLImageElement | null>
  isFullscreen?: boolean
}

function GridOverlay({ divisions }: { divisions: number }) {
  const lines: React.ReactElement[] = []
  for (let i = 1; i < divisions; i++) {
    const pct = `${(i / divisions) * 100}%`
    lines.push(
      <line key={`h${i}`} x1="0" y1={pct} x2="100%" y2={pct} stroke="rgba(255,255,255,0.3)" strokeWidth="1" />,
      <line key={`v${i}`} x1={pct} y1="0" x2={pct} y2="100%" stroke="rgba(255,255,255,0.3)" strokeWidth="1" />,
    )
  }
  return (
    <svg style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' } as any}>
      {lines}
    </svg>
  )
}

export function ZoomableImage({ source, alt, gridDivisions = 0, imgRef, isFullscreen }: Props) {
  return (
    <TransformWrapper
      initialScale={1}
      minScale={0.2}
      maxScale={15}
      centerOnInit
      doubleClick={{ mode: 'reset' }}
    >
      {({ resetTransform }) => (
        <>
          <TransformComponent
            wrapperStyle={{ width: '100%', height: '100%' } as any}
            contentStyle={{ position: 'relative', lineHeight: 0 } as any}
          >
            <img
              ref={imgRef as any}
              src={source}
              alt={alt}
              style={{
                display: 'block',
                maxWidth: 'calc(100vw - 2rem)',
                maxHeight: isFullscreen ? 'calc(100vh - 2rem)' : 'calc(100vh - 200px)',
                userSelect: 'none',
              }}
              draggable={false}
            />
            {gridDivisions > 0 && <GridOverlay divisions={gridDivisions} />}
          </TransformComponent>
          <TouchableOpacity
            style={[styles.resetBtn, isFullscreen && { bottom: 84 }]}
            onPress={() => resetTransform()}
            activeOpacity={0.8}
          >
            <Text style={styles.resetText}>Reset</Text>
          </TouchableOpacity>
        </>
      )}
    </TransformWrapper>
  )
}

const styles = StyleSheet.create({
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
})
