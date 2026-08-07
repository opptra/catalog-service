import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/useAuth'

/**
 * Layout route guarding every authenticated page.
 *
 * This is a layout route rather than a per-page wrapper on purpose: nesting a
 * route under it is the only way to add a page, so a new page is protected by
 * construction instead of by remembering to wrap it.
 */
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
    // Carry the attempted location so signing in returns the user to the page
    // they were on rather than dumping them at the top of the app.
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  return <Outlet />
}

export default RequireAuth
