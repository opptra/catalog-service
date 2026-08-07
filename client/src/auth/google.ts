interface GoogleCredentialResponse {
  credential: string
}

interface GoogleNotification {
  isDismissedMoment?: () => boolean
  getMomentType?: () => string
}

interface GoogleAccountsId {
  initialize: (config: {
    client_id: string
    callback: (response: GoogleCredentialResponse) => void
    auto_select?: boolean
    itp_support?: boolean
    cancel_on_tap_outside?: boolean
  }) => void
  prompt: (momentListener?: (notification: GoogleNotification) => void) => void
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

/**
 * How long to wait for Google to hand back a credential.
 *
 * Settling with `null` only means "no token yet" — if the user goes on to
 * complete an account chooser afterwards, the credential callback still fires
 * and signs them in via `credentialListener`. So this can be short.
 */
const PROMPT_TIMEOUT_MS = 10000

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
    // Lets Google re-issue a token with no user interaction when there is a
    // single approved session. Defaults to false — without it every renewal
    // demands a click, which is what made silent refresh impossible here.
    auto_select: true,
    // Upgraded One Tap flow on ITP browsers (Safari, Firefox).
    itp_support: true,
    // A stray click elsewhere on the page shouldn't cancel a renewal.
    cancel_on_tap_outside: false,
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

/**
 * Ask Google for a fresh ID token, without user interaction where possible.
 *
 * Resolves to `null` when Google cannot produce one — the user's Google session
 * has ended, or the browser blocked the attempt. Callers treat that as "show the
 * sign-in screen", never as a hard error.
 */
export async function requestSilentIdToken(): Promise<string | null> {
  if (!(await whenGoogleReady())) return null
  ensureInitialized()
  if (!window.google) return null

  return new Promise((resolve) => {
    let settled = false

    const settle = (token: string | null) => {
      if (settled) return
      settled = true
      clearTimeout(timeoutId)
      pendingSilentResolvers = pendingSilentResolvers.filter((r) => r !== settle)
      resolve(token)
    }

    const timeoutId = setTimeout(() => settle(null), PROMPT_TIMEOUT_MS)
    pendingSilentResolvers.push(settle)

    window.google!.accounts.id.prompt((notification) => {
      // Under FedCM — now the only One Tap path, since `use_fedcm_for_prompt`
      // is deprecated and ignored — `isNotDisplayed()` and `isDisplayMoment()`
      // are unsupported. Only dismissal is reported reliably; every other
      // outcome falls through to the timeout above.
      if (notification.isDismissedMoment?.()) settle(null)
    })
  })
}

/**
 * Stop Google from silently signing the user straight back in.
 *
 * Without this an explicit sign-out is undone by the next auto-select and the
 * user can never actually leave.
 */
export async function disableAutoSelect(): Promise<void> {
  if (!(await whenGoogleReady())) return
  window.google?.accounts.id.disableAutoSelect()
}
