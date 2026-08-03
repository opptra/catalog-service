import { useEffect } from 'react'
import { Navigate } from 'react-router-dom'
import opptraLogo from '../assets/opptra-logo.png'
import GoogleSignInButton from '../components/GoogleSignInButton'
import { useAuth } from '../auth/useAuth'
import { getSelectedBrandId } from '../data/brands'

function Login() {
  const { user, loading } = useAuth()

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
    return <Navigate to={getSelectedBrandId() ? '/workspace' : '/brands'} replace />
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
