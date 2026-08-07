export const TOKEN_STORAGE_KEY = 'google_id_token'

const STORAGE_KEY = TOKEN_STORAGE_KEY

/**
 * Renew this far ahead of the token's own expiry.
 *
 * Google ID tokens live exactly one hour and cannot be extended — the only way
 * to stay signed in is to obtain a new one before the current one lapses.
 * Renewing early means a request never races the expiry boundary, so a 401
 * becomes an exceptional event rather than an hourly certainty.
 */
const RENEW_AHEAD_MS = 5 * 60 * 1000

/** Treat a token as spent slightly before `exp` to absorb clock drift. */
const EXPIRY_SKEW_MS = 30 * 1000

interface TokenClaims {
  exp?: number
  sub?: string
  email?: string
  name?: string
}

/** Decode a JWT payload. The signature is verified server-side; this only reads claims. */
function decodeClaims(token: string): TokenClaims | null {
  const payload = token.split('.')[1]
  if (!payload) return null

  try {
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, '=')
    // atob yields a binary string; percent-decode it so non-ASCII claims
    // (accented names) survive rather than corrupting the JSON.
    const json = decodeURIComponent(
      atob(padded)
        .split('')
        .map((char) => `%${char.charCodeAt(0).toString(16).padStart(2, '0')}`)
        .join(''),
    )
    return JSON.parse(json) as TokenClaims
  } catch {
    return null
  }
}

function expiryMs(token: string): number | null {
  const exp = decodeClaims(token)?.exp
  return typeof exp === 'number' ? exp * 1000 : null
}

function readStoredToken(): string | null {
  const fromLocal = localStorage.getItem(STORAGE_KEY)
  if (fromLocal) return fromLocal

  // Migrate older session-scoped tokens so open tabs keep working after the switch.
  const fromSession = sessionStorage.getItem(STORAGE_KEY)
  if (fromSession) {
    localStorage.setItem(STORAGE_KEY, fromSession)
    sessionStorage.removeItem(STORAGE_KEY)
    return fromSession
  }

  return null
}

let idToken: string | null = readStoredToken()

export function getIdToken(): string | null {
  return idToken
}

export function setIdToken(token: string): void {
  idToken = token
  localStorage.setItem(STORAGE_KEY, token)
  sessionStorage.removeItem(STORAGE_KEY)
}

export function clearIdToken(): void {
  idToken = null
  localStorage.removeItem(STORAGE_KEY)
  sessionStorage.removeItem(STORAGE_KEY)
}

/** Re-read storage after another tab wrote to it, and return the current token. */
export function reloadFromStorage(): string | null {
  idToken = readStoredToken()
  return idToken
}

/** Whether the token is past its usable life. Unparseable tokens count as expired. */
export function isExpired(token: string): boolean {
  const expiry = expiryMs(token)
  if (expiry === null) return true
  return Date.now() >= expiry - EXPIRY_SKEW_MS
}

/** Whether the token is close enough to expiry that it should be renewed now. */
export function needsRenewal(token: string): boolean {
  const expiry = expiryMs(token)
  if (expiry === null) return true
  return Date.now() >= expiry - RENEW_AHEAD_MS
}

/** Milliseconds until this token should be renewed, floored at zero. */
export function msUntilRenewal(token: string): number | null {
  const expiry = expiryMs(token)
  if (expiry === null) return null
  return Math.max(0, expiry - RENEW_AHEAD_MS - Date.now())
}
