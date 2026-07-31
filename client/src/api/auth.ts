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
  const { data } = await api.post<User>('/auth/google', { id_token: idToken })
  return data
}
