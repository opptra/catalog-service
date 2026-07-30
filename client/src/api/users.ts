import api from './axios'

export interface User {
  id: number
  external_id: string
  email: string | null
  name: string | null
  created_at: string
  updated_at: string
}

export async function getCurrentUser(): Promise<User> {
  const { data } = await api.get<User>('/users/me')
  return data
}
