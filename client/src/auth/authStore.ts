import { create } from 'zustand'
import { loginWithGoogle, type User } from '../api/auth'
import { setCredentialListener } from './google'
import { clearIdToken, getIdToken, setIdToken } from './tokenStore'

interface AuthState {
  user: User | null
  loading: boolean
  signOut: () => void
  handleCredential: (idToken: string) => Promise<void>
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  loading: true,

  signOut: () => {
    clearIdToken()
    set({ user: null })
  },

  handleCredential: async (idToken: string) => {
    setIdToken(idToken)
    try {
      const user = await loginWithGoogle(idToken)
      set({ user })
    } catch {
      clearIdToken()
      set({ user: null })
    }
  },
}))

let bootstrapped = false

/** Wire Google credential handling and restore any existing session once. */
export function bootstrapAuth(): void {
  if (bootstrapped) return
  bootstrapped = true

  setCredentialListener((idToken) => {
    void useAuthStore.getState().handleCredential(idToken)
  })

  const existingToken = getIdToken()
  if (!existingToken) {
    useAuthStore.setState({ loading: false })
    return
  }

  loginWithGoogle(existingToken)
    .then((user) => useAuthStore.setState({ user }))
    .catch(() => clearIdToken())
    .finally(() => useAuthStore.setState({ loading: false }))
}
