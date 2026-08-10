import axios, { type InternalAxiosRequestConfig } from 'axios'
import { requestSilentIdToken } from '../auth/google'
import { clearIdToken, getIdToken, setIdToken } from '../auth/tokenStore'

interface RetryableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean
}

const api = axios.create({
  // Same-origin `/api` locally (Vite proxy) and in prod (nginx).
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.request.use((config) => {
  const token = getIdToken()
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

    const config = error.config as RetryableConfig
    if (config._retried) {
      clearIdToken()
      throw error
    }
    config._retried = true

    const newToken = await requestSilentIdToken()
    if (!newToken) {
      clearIdToken()
      throw error
    }

    setIdToken(newToken)
    return api(config)
  },
)

export default api
