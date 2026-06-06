import React from 'react'
import { View, TouchableOpacity, Text, StyleSheet } from 'react-native'
import { Image } from 'expo-image'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated'

interface Props {
  readonly source: string
  readonly alt?: string
  readonly gridDivisions?: number
  readonly imgRef?: any       // web-only, ignored on native
  readonly isFullscreen?: boolean  // web-only, ignored on native
}

function GridOverlay({ divisions }: { readonly divisions: number }) {
  const lines: React.ReactElement[] = []
  for (let i = 1; i < divisions; i++) {
    const pct = `${(i / divisions) * 100}%` as any
    lines.push(
      <View key={`h${i}`} style={{ position: 'absolute', top: pct, left: 0, right: 0, height: 1, backgroundColor: 'rgba(255,255,255,0.3)' }} />,
      <View key={`v${i}`} style={{ position: 'absolute', left: pct, top: 0, bottom: 0, width: 1, backgroundColor: 'rgba(255,255,255,0.3)' }} />,
    )
  }
  return <View style={StyleSheet.absoluteFill} pointerEvents="none">{lines}</View>
}

export function ZoomableImage({ source, gridDivisions = 0 }: Props) {
  const scale = useSharedValue(1)
  const savedScale = useSharedValue(1)
  const translateX = useSharedValue(0)
  const translateY = useSharedValue(0)
  const savedTranslateX = useSharedValue(0)
  const savedTranslateY = useSharedValue(0)

  const pinchGesture = Gesture.Pinch()
    .onStart(() => {
      savedScale.value = scale.value
    })
    .onUpdate((e) => {
      scale.value = Math.min(Math.max(savedScale.value * e.scale, 0.5), 10)
    })
    .onEnd(() => {
      savedScale.value = scale.value
    })

  const panGesture = Gesture.Pan()
    .averageTouches(true)
    .minPointers(2)
    .onStart(() => {
      savedTranslateX.value = translateX.value
      savedTranslateY.value = translateY.value
    })
    .onUpdate((e) => {
      translateX.value = savedTranslateX.value + e.translationX
      translateY.value = savedTranslateY.value + e.translationY
    })
    .onEnd(() => {
      savedTranslateX.value = translateX.value
      savedTranslateY.value = translateY.value
    })

  const composed = Gesture.Simultaneous(pinchGesture, panGesture)

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [
      { translateX: translateX.value },
      { translateY: translateY.value },
      { scale: scale.value },
    ],
  }))

  const reset = () => {
    scale.value = withTiming(1)
    savedScale.value = 1
    translateX.value = withTiming(0)
    translateY.value = withTiming(0)
    savedTranslateX.value = 0
    savedTranslateY.value = 0
  }

  return (
    <View style={styles.container}>
      <GestureDetector gesture={composed}>
        <Animated.View style={[StyleSheet.absoluteFill, animatedStyle]}>
          <Image source={{ uri: source }} style={styles.image} contentFit="contain" />
          {gridDivisions > 0 && <GridOverlay divisions={gridDivisions} />}
        </Animated.View>
      </GestureDetector>
      <TouchableOpacity style={styles.resetBtn} onPress={reset} activeOpacity={0.8}>
        <Text style={styles.resetText}>Reset</Text>
      </TouchableOpacity>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    overflow: 'hidden',
  },
  image: {
    flex: 1,
  },
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
