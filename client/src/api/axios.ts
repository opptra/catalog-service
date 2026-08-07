import axios, { type InternalAxiosRequestConfig } from 'axios'
import { abandonSession, ensureFreshToken, renewToken } from '../auth/session'

declare module 'axios' {
  interface AxiosRequestConfig {
    /** Set on the sign-in call itself, which carries its own token and must not recurse. */
    skipAuthRefresh?: boolean
  }
}

interface AuthAwareConfig extends InternalAxiosRequestConfig {
  _retried?: boolean
}

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  headers: {
    'Content-Type': 'application/json',
  },
})

// Renew *before* sending rather than reacting to a 401. A token near expiry is
// replaced up front, so the 401 path below stays an exception rather than
// something every user hits once an hour.
api.interceptors.request.use(async (config) => {
  if ((config as AuthAwareConfig).skipAuthRefresh) return config

  const token = await ensureFreshToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  async (error: unknown) => {
    if (!axios.isAxiosError(error) || error.response?.status !== 401 || !error.config) {
      throw error
    }

    const config = error.config as AuthAwareConfig
    if (config.skipAuthRefresh || config._retried) {
      // Either the sign-in call itself failed, or a request failed again using a
      // token we had just renewed — the session is genuinely gone.
      if (!config.skipAuthRefresh) abandonSession()
      throw error
    }
    config._retried = true

    // `renewToken` is single-flight, so a page firing several requests at mount
    // produces one Google round-trip rather than one per request.
    if (!(await renewToken())) {
      abandonSession()
      throw error
    }

    // Re-running the request re-enters the request interceptor, which attaches
    // the newly issued token.
    return api(config)
  },
)

export default api
