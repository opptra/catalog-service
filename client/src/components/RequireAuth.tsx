import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/useAuth'
import { loginPath } from '../lib/brandPath'

function RequireAuth() {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <div className="app-loading">
        <p>Loading…</p>
      </div>
    )
  }

  if (!user) {
    return <Navigate to={loginPath(`${location.pathname}${location.search}`)} replace />
  }

  return <Outlet />
}

export default RequireAuth
