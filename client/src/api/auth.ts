import axios from 'axios'
import api from './axios'

export interface User {
  id: number
  external_id: string
  email: string | null
  name: string | null
  created_at: string
  updated_at: string
}

export async function loginWithGoogle(idToken: string): Promise<User> {
  const { data } = await api.post<User>(
    '/auth/google',
    { id_token: idToken },
    // This call *is* the sign-in; it must not trigger the renew-and-retry path.
    { skipAuthRefresh: true },
  )
  return data
}

/**
 * Whether the server actually rejected the credentials.
 *
 * Worth distinguishing: a 401 is a real answer about the session, while a 5xx or
 * a dropped connection says nothing about it and must not sign the user out.
 */
export function isUnauthorized(error: unknown): boolean {
  return axios.isAxiosError(error) && error.response?.status === 401
}
