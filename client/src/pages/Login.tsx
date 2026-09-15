import { useEffect } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import opptraLogo from '../assets/opptra-logo.png'
import GoogleSignInButton from '../components/GoogleSignInButton'
import { useAuth } from '../auth/useAuth'
import { useBrands } from '../brands/useBrands'
import { brandPath, isSafeInternalPath, readNextParam } from '../lib/brandPath'

function Login() {
  const { user, loading, loginError } = useAuth()
  const { selectedBrand } = useBrands()
  const [searchParams] = useSearchParams()
  const next = readNextParam(searchParams)

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
    if (next != null && isSafeInternalPath(next)) {
      return <Navigate to={next} replace />
    }
    if (selectedBrand) {
      return <Navigate to={brandPath(selectedBrand.id, '/workspace')} replace />
    }
    return <Navigate to="/brands" replace />
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
        {loginError ? <p className="login-card__error">{loginError}</p> : null}
        <p className="login-card__footnote">Accounts are provisioned by your account manager.</p>
      </div>
    </main>
  )
}

export default Login
