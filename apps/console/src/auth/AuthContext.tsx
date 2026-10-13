import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, setUnauthorizedHandler, tokenStore, unwrap, type User } from '../api/client'

interface AuthState {
  user: User | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  can: (permission: string) => boolean
}

const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState<boolean>(() => tokenStore.get() !== null)

  const logout = useCallback(() => {
    tokenStore.clear()
    setUser(null)
    qc.clear()
  }, [qc])

  useEffect(() => { setUnauthorizedHandler(logout) }, [logout])

  // Restore the session by asking the server who the token belongs to.
  useEffect(() => {
    if (!tokenStore.get()) return
    unwrap(api.GET('/auth/me'))
      .then(setUser)
      .catch(() => tokenStore.clear())
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const res = await unwrap(api.POST('/auth/login', { body: { username, password } }))
    tokenStore.set(res.access_token)
    setUser(res.user)
  }, [])

  const value = useMemo<AuthState>(() => ({
    user, loading, login, logout,
    // UI hint only. Every permission is enforced again on the server for each request.
    can: (p) => !!user?.permissions.includes(p),
  }), [user, loading, login, logout])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAuth outside AuthProvider')
  return v
}
