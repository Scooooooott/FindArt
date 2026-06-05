import React, { createContext, useContext, useEffect, useState } from 'react'
import { getOrCreateSessionId } from '../lib/session'
import { setSessionId } from '../lib/api'

const SessionContext = createContext<string | null>(null)

/**
 * Initialises the anonymous session UUID on mount and injects it into the
 * API module so every subsequent request carries the X-Session-ID header.
 * Renders children immediately — the null → string transition is transparent
 * to most consumers (history/favourites hooks simply stay disabled until ready).
 */
export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [sessionId, setSessionIdState] = useState<string | null>(null)

  useEffect(() => {
    getOrCreateSessionId().then(id => {
      setSessionIdState(id)
      setSessionId(id)  // inject into api.ts module-level variable
    })
  }, [])

  return (
    <SessionContext.Provider value={sessionId}>
      {children}
    </SessionContext.Provider>
  )
}

/** Returns the session UUID once initialised, null while initialising. */
export function useSessionId(): string | null {
  return useContext(SessionContext)
}
