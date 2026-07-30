const STORAGE_KEY = 'google_id_token'

let idToken: string | null = sessionStorage.getItem(STORAGE_KEY)

export function getIdToken(): string | null {
  return idToken
}

export function setIdToken(token: string): void {
  idToken = token
  sessionStorage.setItem(STORAGE_KEY, token)
}

export function clearIdToken(): void {
  idToken = null
  sessionStorage.removeItem(STORAGE_KEY)
}
