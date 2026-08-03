import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../auth/useAuth'

interface RequireAuthProps {
  children: ReactNode
}

function RequireAuth({ children }: RequireAuthProps) {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div className="app-loading">
        <p>Loading…</p>
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  return children
}

export default RequireAuth
