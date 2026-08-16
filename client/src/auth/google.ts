interface GoogleCredentialResponse {
  credential: string
}

interface GoogleAccountsId {
  initialize: (config: {
    client_id: string
    callback: (response: GoogleCredentialResponse) => void
  }) => void
  renderButton: (parent: HTMLElement, options: Record<string, unknown>) => void
  disableAutoSelect: () => void
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
      credentialListener?.(response.credential)
    },
  })
  initialized = true
}

export function setCredentialListener(listener: CredentialListener | null): void {
  credentialListener = listener
}

export async function renderSignInButton(
  parent: HTMLElement,
  options?: { width?: number },
): Promise<void> {
  if (!(await whenGoogleReady())) return
  ensureInitialized()
  window.google?.accounts.id.renderButton(parent, {
    theme: 'outline',
    size: 'large',
    shape: 'pill',
    text: 'signin_with',
    width: options?.width ?? 320,
  })
}

export async function disableAutoSelect(): Promise<void> {
  if (!(await whenGoogleReady())) return
  ensureInitialized()
  window.google?.accounts.id.disableAutoSelect()
}
