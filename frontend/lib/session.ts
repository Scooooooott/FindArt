import { Platform } from 'react-native'

const SESSION_KEY = 'findart_session_id'

function generateUUID(): string {
  // crypto.randomUUID() available in modern browsers + Hermes (RN 0.71+)
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  // RFC 4122 v4 fallback
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = (Math.random() * 16) | 0
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16)
  })
}

/**
 * Return the persisted session UUID, generating and storing it on first call.
 * Web: localStorage (sync wrapped in Promise for a uniform interface).
 * Native: @react-native-async-storage/async-storage (truly async).
 */
export async function getOrCreateSessionId(): Promise<string> {
  if (Platform.OS === 'web') {
    let id = localStorage.getItem(SESSION_KEY)
    if (!id) {
      id = generateUUID()
      localStorage.setItem(SESSION_KEY, id)
    }
    return id
  }

  // Dynamic import keeps the web bundle free of AsyncStorage code
  const { default: AsyncStorage } = await import(
    '@react-native-async-storage/async-storage'
  )
  let id = await AsyncStorage.getItem(SESSION_KEY)
  if (!id) {
    id = generateUUID()
    await AsyncStorage.setItem(SESSION_KEY, id)
  }
  return id
}

/** Remove the stored session UUID (used after DELETE /sessions/{id}). */
export async function clearStoredSessionId(): Promise<void> {
  if (Platform.OS === 'web') {
    localStorage.removeItem(SESSION_KEY)
    return
  }
  const { default: AsyncStorage } = await import(
    '@react-native-async-storage/async-storage'
  )
  await AsyncStorage.removeItem(SESSION_KEY)
}
