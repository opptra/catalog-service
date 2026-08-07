import { disableAutoSelect, requestSilentIdToken } from './google'
import {
  TOKEN_STORAGE_KEY,
  clearIdToken,
  getIdToken,
  isExpired,
  msUntilRenewal,
  needsRenewal,
  reloadFromStorage,
  setIdToken,
} from './tokenStore'

/**
 * Owns the lifetime of the Google ID token.
 *
 * Google ID tokens expire after one hour and cannot be extended, so staying
 * signed in means continuously obtaining new ones. Everything that decides
 * *when* to do that lives here, so no page, store, or request site has to think
 * about token expiry — they ask for a token and get a usable one, or `null`
 * meaning the user genuinely has to sign in again.
 */

/** Retry delay after a background renewal fails while the token is still valid. */
const RENEWAL_RETRY_MS = 60 * 1000

type AuthLostListener = () => void

let authLostListener: AuthLostListener | null = null
let inFlightRenewal: Promise<string | null> | null = null
let renewalTimer: ReturnType<typeof setTimeout> | null = null

/** Register the single place that reacts to the session going away. */
export function setAuthLostListener(listener: AuthLostListener | null): void {
  authLostListener = listener
}

function cancelScheduledRenewal(): void {
  if (renewalTimer !== null) {
    clearTimeout(renewalTimer)
    renewalTimer = null
  }
}

function scheduleRenewal(): void {
  cancelScheduledRenewal()

  const token = getIdToken()
  if (!token) return

  const delay = msUntilRenewal(token)
  if (delay === null) return

  renewalTimer = setTimeout(() => void renewInBackground(), delay)
}

/** Take on a freshly issued token and arm the next renewal. */
export function adoptToken(token: string): void {
  setIdToken(token)
  scheduleRenewal()
}

/**
 * Give up the session and notify the app — once, from one place.
 *
 * Previously the axios interceptor cleared the token without telling the auth
 * store, leaving React rendering a signed-in UI whose every request 401s.
 */
export function abandonSession(): void {
  cancelScheduledRenewal()
  clearIdToken()
  authLostListener?.()
}

/** Ask Google for a new token. Concurrent callers share a single attempt. */
export function renewToken(): Promise<string | null> {
  if (inFlightRenewal) return inFlightRenewal

  inFlightRenewal = requestSilentIdToken()
    .then((token) => {
      if (token) adoptToken(token)
      return token
    })
    .catch(() => null)
    .finally(() => {
      inFlightRenewal = null
    })

  return inFlightRenewal
}

async function renewInBackground(): Promise<void> {
  if (await renewToken()) return

  // The renewal failed, but the current token may still have life in it. Try
  // again shortly rather than signing the user out while they can still work.
  const current = getIdToken()
  if (current && !isExpired(current)) {
    cancelScheduledRenewal()
    renewalTimer = setTimeout(() => void renewInBackground(), RENEWAL_RETRY_MS)
  }
}

/**
 * The token to attach to an outbound request. `null` means the user must sign
 * in again.
 *
 * Only an already-expired token makes the caller wait. That case still happens
 * despite the scheduled renewal — a sleeping laptop doesn't fire timers, so a
 * machine waking after a few hours lands here.
 */
export async function ensureFreshToken(): Promise<string | null> {
  const token = getIdToken()
  if (!token) return null

  if (isExpired(token)) return renewToken()

  if (needsRenewal(token)) {
    // Still usable: send this request now and let the renewal run behind it,
    // rather than holding the request on a Google round-trip.
    void renewToken()
  }

  return token
}

/** Sign out locally and stop Google from immediately signing the user back in. */
export async function endSession(): Promise<void> {
  cancelScheduledRenewal()
  clearIdToken()
  await disableAutoSelect()
}

/**
 * Keep tabs in step: adopt a token a sibling tab obtained instead of each tab
 * prompting Google separately, and follow a sign-out across every tab.
 *
 * `storage` fires only in *other* tabs, so this cannot loop back on itself.
 */
export function startCrossTabSync(): void {
  window.addEventListener('storage', (event) => {
    if (event.key !== TOKEN_STORAGE_KEY) return

    const token = reloadFromStorage()
    if (token && !isExpired(token)) {
      scheduleRenewal()
    } else {
      abandonSession()
    }
  })
}
