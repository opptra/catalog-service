import { create } from 'zustand'
import { loginWithGoogle, logout, type User } from '../api/auth'
import { getCurrentUser } from '../api/users'
import { setUnauthorizedHandler } from '../api/axios'
import { DEV_MODE } from '../devMode'
import { disableAutoSelect, setCredentialListener } from './google'

interface AuthState {
  user: User | null
  loading: boolean
  loginError: string | null
  signOut: () => Promise<void>
  handleCredential: (idToken: string) => Promise<void>
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  loading: true,
  loginError: null,

  signOut: async () => {
    set({ user: null, loginError: null })
    void disableAutoSelect()
    try {
      await logout()
    } catch {
      // Cookie may already be gone; local sign-out still succeeds.
    }
  },

  handleCredential: async (idToken: string) => {
    set({ loginError: null })
    try {
      const user = await loginWithGoogle(idToken)
      set({ user, loginError: null })
    } catch {
      set({ user: null, loginError: 'Sign-in failed, try again' })
    }
  },
}))

let bootstrapped = false

/** Wire Google credential handling and restore any existing session once. */
export function bootstrapAuth(): void {
  if (bootstrapped) return
  bootstrapped = true

  if (!DEV_MODE) {
    setCredentialListener((idToken) => {
      void useAuthStore.getState().handleCredential(idToken)
    })
  }

  setUnauthorizedHandler(() => {
    const { user } = useAuthStore.getState()
    if (user !== null) {
      void useAuthStore.getState().signOut()
    } else {
      useAuthStore.setState({ user: null })
    }
  })

  getCurrentUser()
    .then((user) => useAuthStore.setState({ user }))
    .catch(() => useAuthStore.setState({ user: null }))
    .finally(() => useAuthStore.setState({ loading: false }))
}
