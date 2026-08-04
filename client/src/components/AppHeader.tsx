import { Link } from 'react-router-dom'
import opptraLogo from '../assets/opptra-logo.png'
import { useAuth } from '../auth/useAuth'

interface AppHeaderProps {
  brandName?: string
  onBrandClick?: () => void
  showExecutionHistory?: boolean
  onExecutionHistoryClick?: () => void
}

function ChevronDownIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path
        d="M3.5 5.25L7 8.75L10.5 5.25"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function AppHeader({
  brandName,
  onBrandClick,
  showExecutionHistory = false,
  onExecutionHistoryClick,
}: AppHeaderProps) {
  const { user, signOut } = useAuth()

  return (
    <header className="app-header">
      <div className="app-header__left">
        <Link to="/brands" className="app-header__brand">
          <img src={opptraLogo} alt="opptra" className="app-header__logo" />
          <span className="app-header__product">Listing Studio</span>
        </Link>

        {brandName ? (
          <div className="app-header__actions">
            <button
              type="button"
              className="app-header__pill"
              onClick={onBrandClick}
              aria-label={`Current brand ${brandName}. Change brand`}
            >
              <span>{brandName}</span>
              <ChevronDownIcon />
            </button>
            {showExecutionHistory ? (
              <button
                type="button"
                className="app-header__pill"
                onClick={onExecutionHistoryClick}
              >
                Execution history
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="app-header__right">
        {user?.email ? <span className="app-header__email">{user.email}</span> : null}
        <button type="button" className="app-header__sign-out" onClick={signOut}>
          sign out
        </button>
      </div>
    </header>
  )
}

export default AppHeader
