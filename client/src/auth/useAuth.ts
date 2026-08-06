import { useAuthStore } from './authStore'

export function useAuth() {
  const user = useAuthStore((state) => state.user)
  const loading = useAuthStore((state) => state.loading)
  const signOut = useAuthStore((state) => state.signOut)

  return { user, loading, signOut }
}
