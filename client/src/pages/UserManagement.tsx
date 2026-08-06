import { useEffect, useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'
import axios from 'axios'
import { inviteBrandUser, listBrandUsers, type BrandUser } from '../api/access'
import { useBrands } from '../brands/useBrands'
import AppHeader from '../components/AppHeader'

const OPPTRA_EMAIL_PATTERN = /^[^\s@]+@opptra\.com$/i

function formatGrantedAt(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

function UserManagement() {
  const { selectedBrand: brand } = useBrands()
  const [users, setUsers] = useState<BrandUser[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [email, setEmail] = useState('')
  const [inviteError, setInviteError] = useState<string | null>(null)
  const [inviteMessage, setInviteMessage] = useState<string | null>(null)
  const [inviting, setInviting] = useState(false)

  useEffect(() => {
    document.title = brand
      ? `Listing Studio · ${brand.name} · Users`
      : 'Listing Studio · Users'
  }, [brand])

  useEffect(() => {
    if (!brand) return

    const brandExternalId = brand.id
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const rows = await listBrandUsers(brandExternalId)
        if (cancelled) return
        setUsers(rows)
      } catch {
        if (cancelled) return
        setError("Couldn't load users for this brand.")
        setUsers([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [brand])

  if (!brand) {
    return <Navigate to="/brands" replace />
  }

  const brandId = brand.id
  const brandName = brand.name

  async function handleInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmed = email.trim().toLowerCase()
    setInviteError(null)
    setInviteMessage(null)

    if (!OPPTRA_EMAIL_PATTERN.test(trimmed)) {
      setInviteError('Only @opptra.com email addresses can be invited.')
      return
    }

    setInviting(true)
    try {
      const invited = await inviteBrandUser(brandId, trimmed)
      setEmail('')
      setInviteMessage(
        invited.created
          ? `Invited ${invited.email}. They can sign in with Google to join.`
          : `${invited.email} already has access.`,
      )
      const rows = await listBrandUsers(brandId)
      setUsers(rows)
    } catch (err) {
      if (axios.isAxiosError(err)) {
        const detail = err.response?.data?.detail
        setInviteError(
          typeof detail === 'string'
            ? detail
            : "Couldn't invite that user. Try again.",
        )
      } else {
        setInviteError("Couldn't invite that user. Try again.")
      }
    } finally {
      setInviting(false)
    }
  }

  return (
    <div className="page-shell">
      <AppHeader brandName={brandName} showExecutionHistory showUserManagement={false} />
      <main className="user-management-page">
        <div className="user-management-page__inner">
          <header className="user-management-page__header">
            <h1 className="user-management-page__title">User management</h1>
            <p className="user-management-page__subtitle">
              Invite Opptra teammates to {brandName} on Listing Studio.
            </p>
          </header>

          <form className="user-management-invite" onSubmit={handleInvite}>
            <label className="user-management-invite__label" htmlFor="invite-email">
              Invite by email
            </label>
            <div className="user-management-invite__row">
              <input
                id="invite-email"
                type="email"
                className="user-management-invite__input"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="name@opptra.com"
                autoComplete="email"
                required
              />
              <button
                type="submit"
                className="btn-primary user-management-invite__submit"
                disabled={inviting || email.trim().length === 0}
              >
                {inviting ? 'Inviting…' : 'Invite'}
              </button>
            </div>
            {inviteError ? <p className="user-management-invite__error">{inviteError}</p> : null}
            {inviteMessage ? (
              <p className="user-management-invite__success">{inviteMessage}</p>
            ) : null}
          </form>

          <section className="user-management-list" aria-label="Brand users">
            <h2 className="user-management-list__title">People with access</h2>
            {loading ? <p className="user-management-list__status">Loading users…</p> : null}
            {!loading && error ? <p className="user-management-list__error">{error}</p> : null}
            {!loading && !error && users.length === 0 ? (
              <p className="user-management-list__status">No users yet. Invite someone above.</p>
            ) : null}
            {!loading && !error && users.length > 0 ? (
              <ul className="user-management-list__items">
                {users.map((item) => (
                  <li key={item.external_id} className="user-management-card">
                    <div className="user-management-card__copy">
                      <p className="user-management-card__name">{item.name}</p>
                      <p className="user-management-card__email">{item.email}</p>
                    </div>
                    <div className="user-management-card__meta">
                      <span
                        className={
                          item.has_signed_in
                            ? 'user-management-card__badge user-management-card__badge--active'
                            : 'user-management-card__badge'
                        }
                      >
                        {item.has_signed_in ? 'Signed in' : 'Invited'}
                      </span>
                      <span className="user-management-card__granted">
                        Added {formatGrantedAt(item.granted_at)}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            ) : null}
          </section>
        </div>
      </main>
    </div>
  )
}

export default UserManagement
