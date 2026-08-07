import { create } from 'zustand'
import { isUnauthorized, loginWithGoogle, type User } from '../api/auth'
import { setCredentialListener } from './google'
import {
  adoptToken,
  endSession,
  renewToken,
  setAuthLostListener,
  startCrossTabSync,
} from './session'
import { getIdToken, isExpired } from './tokenStore'

/** Attempts to confirm a stored session before giving up on it. */
const VERIFY_ATTEMPTS = 3

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
    void endSession()
    set({ user: null, loading: false })
  },

  handleCredential: async (idToken: string) => {
    adoptToken(idToken)
    try {
      const user = await loginWithGoogle(idToken)
      set({ user, loading: false })
    } catch {
      await endSession()
      set({ user: null, loading: false })
    }
  },
}))

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * Confirm a stored token with the server.
 *
 * Only a 401 means the session is over. A server restart or a network blip says
 * nothing about whether the user is signed in, so those are retried — otherwise
 * a routine deploy signs everybody out.
 */
async function verifyStoredSession(token: string): Promise<User | null> {
  for (let attempt = 0; attempt < VERIFY_ATTEMPTS; attempt += 1) {
    try {
      return await loginWithGoogle(token)
    } catch (error) {
      if (isUnauthorized(error)) {
        await endSession()
        return null
      }
      if (attempt === VERIFY_ATTEMPTS - 1) {
        // Out of attempts, but the token is kept: the next page load or request
        // can still succeed once the server is reachable again.
        return null
      }
      await delay(500 * 2 ** attempt)
    }
  }
  return null
}

let bootstrapped = false

/** Wire Google credential handling and restore any existing session once. */
export function bootstrapAuth(): void {
  if (bootstrapped) return
  bootstrapped = true

  // The one place that decides what "session lost" means for the UI. The axios
  // interceptor calls into this instead of clearing the token itself, which is
  // what used to leave a signed-in UI whose every request 401s.
  setAuthLostListener(() => {
    useAuthStore.setState({ user: null, loading: false })
  })

  setCredentialListener((idToken) => {
    void useAuthStore.getState().handleCredential(idToken)
  })

  startCrossTabSync()

  const token = getIdToken()

  if (token && !isExpired(token)) {
    // Re-arm renewal for this token's remaining life, then confirm the session
    // with the server before the app renders.
    adoptToken(token)
    void verifyStoredSession(token).then((user) =>
      useAuthStore.setState({ user, loading: false }),
    )
    return
  }

  // No usable token. Don't hold the UI on a Google round-trip that may need user
  // interaction: show the sign-in screen now and let a silent attempt run behind
  // it. If it succeeds the credential listener above signs the user in, and the
  // login page redirects them onward.
  useAuthStore.setState({ user: null, loading: false })
  void renewToken()
}
