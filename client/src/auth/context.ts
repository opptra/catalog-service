import { createContext } from 'react'
import type { User } from '../api/auth'

export interface AuthContextValue {
  user: User | null
  loading: boolean
  signOut: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)
