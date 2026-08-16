import axios from 'axios'
import { getSelectedBrandId } from '../data/brands'

const api = axios.create({
  // Same-origin `/api` locally (Vite proxy) and in prod (nginx).
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
})

let onUnauthorized: (() => void) | null = null

/** Registered by auth bootstrap to avoid a circular import with the auth store. */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler
}

api.interceptors.request.use((config) => {
  const brandId = getSelectedBrandId()
  if (brandId) {
    config.headers['Brand-Id'] = brandId
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      const url = error.config?.url ?? ''
      const isAuthExchange =
        url.includes('/auth/google') || url.includes('/auth/logout')
      if (!isAuthExchange) {
        onUnauthorized?.()
      }
    }
    return Promise.reject(error)
  },
)

export default api
