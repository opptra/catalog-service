interface GoogleCredentialResponse {
  credential: string
}

interface GoogleNotification {
  isNotDisplayed?: () => boolean
  isSkippedMoment?: () => boolean
}

interface GoogleAccountsId {
  initialize: (config: {
    client_id: string
    callback: (response: GoogleCredentialResponse) => void
  }) => void
  prompt: (momentListener?: (notification: GoogleNotification) => void) => void
  renderButton: (parent: HTMLElement, options: Record<string, unknown>) => void
}

declare global {
  interface Window {
    google?: {
      accounts: {
        id: GoogleAccountsId
      }
    }
  }
}

type CredentialListener = (idToken: string) => void

const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID as string

let initialized = false
let credentialListener: CredentialListener | null = null
let pendingSilentResolvers: Array<(token: string | null) => void> = []

// The GIS script is loaded `async defer`, so `window.google` may not exist yet
// when our components mount. Resolve once it becomes available (or give up).
function whenGoogleReady(): Promise<boolean> {
  if (window.google) return Promise.resolve(true)

  return new Promise((resolve) => {
    const startedAt = Date.now()
    const intervalId = setInterval(() => {
      if (window.google) {
        clearInterval(intervalId)
        resolve(true)
      } else if (Date.now() - startedAt > 10000) {
        clearInterval(intervalId)
        resolve(false)
      }
    }, 100)
  })
}

function ensureInitialized(): void {
  if (initialized || !window.google) return

  window.google.accounts.id.initialize({
    client_id: CLIENT_ID,
    callback: (response) => {
      const resolvers = pendingSilentResolvers
      pendingSilentResolvers = []
      resolvers.forEach((resolve) => resolve(response.credential))
      credentialListener?.(response.credential)
    },
  })
  initialized = true
}

export function setCredentialListener(listener: CredentialListener | null): void {
  credentialListener = listener
}

export async function renderSignInButton(parent: HTMLElement): Promise<void> {
  if (!(await whenGoogleReady())) return
  ensureInitialized()
  window.google?.accounts.id.renderButton(parent, { theme: 'outline', size: 'medium' })
}

export async function requestSilentIdToken(): Promise<string | null> {
  if (!(await whenGoogleReady())) return null
  ensureInitialized()
  if (!window.google) return null

  return new Promise((resolve) => {
    const settle = (token: string | null) => {
      pendingSilentResolvers = pendingSilentResolvers.filter((r) => r !== settle)
      resolve(token)
    }
    pendingSilentResolvers.push(settle)

    const timeoutId = setTimeout(() => settle(null), 5000)

    window.google!.accounts.id.prompt((notification) => {
      if (notification.isNotDisplayed?.() || notification.isSkippedMoment?.()) {
        clearTimeout(timeoutId)
        settle(null)
      }
    })
  })
}
