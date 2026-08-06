import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import opptraLogo from '../assets/opptra-logo.png'
import { useAuth } from '../auth/useAuth'
import { useBrands } from '../brands/useBrands'

interface AppHeaderProps {
  brandName?: string
  showExecutionHistory?: boolean
  onExecutionHistoryClick?: () => void
  showNewBatch?: boolean
  onNewBatchClick?: () => void
  showBatches?: boolean
  onBatchesClick?: () => void
  batchesBadgeCount?: number
}

function PlusIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path
        d="M7 2.75V11.25M2.75 7H11.25"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  )
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
  showExecutionHistory = false,
  onExecutionHistoryClick,
  showNewBatch = false,
  onNewBatchClick,
  showBatches = false,
  onBatchesClick,
  batchesBadgeCount,
}: AppHeaderProps) {
  const { user, signOut } = useAuth()
  const { brands, loading, loadFailed, selectedBrand, selectBrand } = useBrands()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return

    function onPointerDown(event: PointerEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }

    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  function handleSelect(brandId: string, brandNameValue: string) {
    selectBrand({ id: brandId, name: brandNameValue })
    setOpen(false)
    navigate('/workspace')
  }

  return (
    <header className="app-header">
      <div className="app-header__left">
        <Link to="/brands" className="app-header__brand">
          <img src={opptraLogo} alt="opptra" className="app-header__logo" />
          <span className="app-header__product">Listing Studio</span>
        </Link>

        {brandName ? (
          <div className="app-header__actions">
            <div className="app-header__brand-menu" ref={dropdownRef}>
              <button
                type="button"
                className="app-header__pill"
                onClick={() => setOpen((current) => !current)}
                aria-expanded={open}
                aria-haspopup="listbox"
                aria-label={`Current brand ${brandName}. Change brand`}
              >
                <span>{brandName}</span>
                <ChevronDownIcon />
              </button>

              {open ? (
                <div className="app-header__dropdown" role="listbox" aria-label="Available brands">
                  {loading ? <p className="app-header__dropdown-status">Loading brands…</p> : null}

                  {loadFailed ? (
                    <p className="app-header__dropdown-status">
                      Couldn&apos;t load brands. Try again.
                    </p>
                  ) : null}

                  {!loading && !loadFailed && brands.length === 0 ? (
                    <p className="app-header__dropdown-status">
                      No brands available. Contact your admin to get access.
                    </p>
                  ) : null}

                  {!loading && !loadFailed
                    ? brands.map((brand) => {
                        const selected = brand.external_id === selectedBrand?.id
                        return (
                          <button
                            key={brand.external_id}
                            type="button"
                            role="option"
                            aria-selected={selected}
                            className={
                              selected
                                ? 'app-header__dropdown-item app-header__dropdown-item--selected'
                                : 'app-header__dropdown-item'
                            }
                            onClick={() => handleSelect(brand.external_id, brand.name)}
                          >
                            {brand.name}
                          </button>
                        )
                      })
                    : null}
                </div>
              ) : null}
            </div>

            {showNewBatch ? (
              <button type="button" className="app-header__cta" onClick={onNewBatchClick}>
                <PlusIcon />
                New batch
              </button>
            ) : null}

            {showBatches ? (
              <button type="button" className="app-header__pill" onClick={onBatchesClick}>
                Batches
                {batchesBadgeCount != null && batchesBadgeCount > 0 ? (
                  <span className="app-header__badge">{batchesBadgeCount}</span>
                ) : null}
              </button>
            ) : null}

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
