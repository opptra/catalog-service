import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { loginWithGoogle, type User } from '../api/auth'
import { clearSelectedBrandId } from '../data/brands'
import { AuthContext } from './context'
import { setCredentialListener } from './google'
import { clearIdToken, getIdToken, setIdToken } from './tokenStore'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const handleCredential = useCallback(async (idToken: string) => {
    setIdToken(idToken)
    try {
      setUser(await loginWithGoogle(idToken))
    } catch {
      clearIdToken()
      setUser(null)
    }
  }, [])

  const signOut = useCallback(() => {
    clearIdToken()
    clearSelectedBrandId()
    setUser(null)
  }, [])

  useEffect(() => {
    setCredentialListener(handleCredential)
    return () => setCredentialListener(null)
  }, [handleCredential])

  useEffect(() => {
    const existingToken = getIdToken()
    if (!existingToken) {
      setLoading(false)
      return
    }
    loginWithGoogle(existingToken)
      .then(setUser)
      .catch(() => clearIdToken())
      .finally(() => setLoading(false))
  }, [])

  return (
    <AuthContext.Provider value={{ user, loading, signOut }}>{children}</AuthContext.Provider>
  )
}
