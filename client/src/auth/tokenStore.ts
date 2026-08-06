const STORAGE_KEY = 'google_id_token'

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
