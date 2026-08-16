import api from './axios'
import type { User } from './users'

export type { User }

export async function loginWithGoogle(idToken: string): Promise<User> {
  const { data } = await api.post<User>('/auth/google', { id_token: idToken })
  return data
}

export async function logout(): Promise<void> {
  await api.post('/auth/logout')
}
