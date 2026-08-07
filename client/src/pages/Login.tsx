import { useEffect } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import opptraLogo from '../assets/opptra-logo.png'
import GoogleSignInButton from '../components/GoogleSignInButton'
import { useAuth } from '../auth/useAuth'
import { useBrands } from '../brands/useBrands'

/** Set by RequireAuth when it redirects an unauthenticated visitor here. */
interface LoginLocationState {
  from?: { pathname?: string }
}

function Login() {
  const { user, loading } = useAuth()
  const { selectedBrand } = useBrands()
  const location = useLocation()

  useEffect(() => {
    document.title = 'Listing Studio · Sign in'
  }, [])

  if (loading) {
    return (
      <div className="app-loading">
        <p>Loading…</p>
      </div>
    )
  }

  if (user) {
    // Return the user to the page they were on when the session lapsed, but
    // only once a brand is selected — the inner pages need that context.
    const from = (location.state as LoginLocationState | null)?.from?.pathname
    const fallback = selectedBrand ? '/workspace' : '/brands'
    const destination = selectedBrand && from && from !== '/login' ? from : fallback
    return <Navigate to={destination} replace />
  }

  return (
    <main className="login-page">
      <div className="login-card">
        <img src={opptraLogo} alt="opptra" className="login-card__logo" />
        <h1 className="login-card__title">Listing Studio</h1>
        <p className="login-card__subtitle">Sign in to generate marketplace listings.</p>
        <div className="login-card__google">
          <GoogleSignInButton width={380} />
        </div>
        <p className="login-card__footnote">Accounts are provisioned by your account manager.</p>
      </div>
    </main>
  )
}

export default Login
