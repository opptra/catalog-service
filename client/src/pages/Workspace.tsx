import { useEffect, useRef, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { listJobs, type JobListItem } from '../api/jobs'
import { useBrands } from '../brands/useBrands'
import AppHeader from '../components/AppHeader'

interface ExecutionSection {
  key: string
  label: string
  items: JobListItem[]
}

function PlusIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M8 3.25V12.75M3.25 8H12.75"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  )
}

function SearchIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.5" />
      <path d="M10.5 10.5L13.5 13.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

function StatusIcon({ status }: { status: string }) {
  if (status === 'COMPLETED') {
    return (
      <span className="execution-card__icon execution-card__icon--done" aria-hidden="true">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path
            d="M3.5 7.25L5.75 9.5L10.5 4.5"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
    )
  }

  if (status === 'FAILED') {
    return (
      <span className="execution-card__icon execution-card__icon--failed" aria-hidden="true">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path
            d="M4.5 4.5L9.5 9.5M9.5 4.5L4.5 9.5"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
          />
        </svg>
      </span>
    )
  }

  return (
    <span className="execution-card__icon execution-card__icon--pending" aria-hidden="true">
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
        <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    </span>
  )
}

function startOfLocalDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
}

function formatShortDateTime(iso: string): string {
  const date = new Date(iso)
  const day = date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
  const time = date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  return `${day}, ${time}`
}

function sectionLabelFor(iso: string, now: Date): string {
  const day = startOfLocalDay(new Date(iso))
  const today = startOfLocalDay(now)
  const yesterday = today - 24 * 60 * 60 * 1000
  if (day === today) return 'Today'
  if (day === yesterday) return 'Yesterday'
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })
}

function statusLabel(status: string): string {
  if (status === 'COMPLETED') return 'Completed'
  if (status === 'FAILED') return 'Failed'
  return 'In progress'
}

function skuProgressLabel(item: JobListItem): string {
  const processed = item.completed_sku_count + item.failed_sku_count
  const total = item.sku_count
  if (total === 0) return 'No SKUs'
  if (item.pending_sku_count > 0) {
    return `${processed} of ${total} SKUs processed · ${item.pending_sku_count} pending`
  }
  if (item.failed_sku_count > 0) {
    return `${item.completed_sku_count} of ${total} SKUs processed · ${item.failed_sku_count} failed`
  }
  return `${item.completed_sku_count} of ${total} SKUs processed`
}

function groupByDay(items: JobListItem[]): ExecutionSection[] {
  const now = new Date()
  const sections: ExecutionSection[] = []
  const indexByKey = new Map<string, number>()

  for (const item of items) {
    const label = sectionLabelFor(item.started_at, now)
    const key = label
    const existing = indexByKey.get(key)
    if (existing == null) {
      indexByKey.set(key, sections.length)
      sections.push({ key, label, items: [item] })
    } else {
      sections[existing].items.push(item)
    }
  }

  return sections
}

function hasInProgressJobs(jobs: JobListItem[]): boolean {
  return jobs.some((item) => item.status === 'PENDING' || item.pending_sku_count > 0)
}

const EXECUTIONS_POLL_MS = 8_000
const EXECUTIONS_PAGE_SIZE = 50

function Workspace() {
  const navigate = useNavigate()
  const { selectedBrand: brand } = useBrands()
  const brandId = brand?.id
  const [items, setItems] = useState<JobListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [nextOffset, setNextOffset] = useState<number | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const itemsRef = useRef(items)
  itemsRef.current = items
  const loadMoreRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    document.title = brand ? `Listing Studio · ${brand.name}` : 'Listing Studio'
  }, [brand])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedQuery(query.trim().toLowerCase())
    }, 300)
    return () => window.clearTimeout(timer)
  }, [query])

  useEffect(() => {
    if (!brandId) return

    const selectedBrandId = brandId
    let cancelled = false
    let pollId: number | undefined
    let refreshInFlight = false

    async function loadFirstPage(options: { showLoading: boolean }) {
      if (refreshInFlight) return
      refreshInFlight = true
      const showRefreshHint = !options.showLoading && hasInProgressJobs(itemsRef.current)
      if (options.showLoading) {
        setLoading(true)
        setError(null)
      } else if (showRefreshHint) {
        setRefreshing(true)
      }
      try {
        const response = await listJobs(selectedBrandId, {
          offset: 0,
          limit: EXECUTIONS_PAGE_SIZE,
        })
        if (cancelled) return
        setItems((current) => {
          if (options.showLoading || current.length <= response.items.length) {
            return response.items
          }
          const seen = new Set(response.items.map((item) => item.external_id))
          const remainder = current.filter((item) => !seen.has(item.external_id))
          return [...response.items, ...remainder]
        })
        setNextOffset((current) => {
          if (options.showLoading || current == null) return response.next_offset
          const preservedLength = Math.max(itemsRef.current.length, response.items.length)
          return response.has_more ? preservedLength : null
        })
        setHasMore((current) => (options.showLoading ? response.has_more : current || response.has_more))
        if (options.showLoading) setError(null)
      } catch {
        if (cancelled) return
        // Keep the current list + search intact on background refresh failures.
        if (options.showLoading) {
          setError("Couldn't load executions. Try again.")
          setItems([])
        }
      } finally {
        refreshInFlight = false
        if (cancelled) return
        if (options.showLoading) setLoading(false)
        else setRefreshing(false)
      }
    }

    void loadFirstPage({ showLoading: true }).then(() => {
      if (cancelled) return
      pollId = window.setInterval(() => {
        void loadFirstPage({ showLoading: false })
      }, EXECUTIONS_POLL_MS)
    })

    return () => {
      cancelled = true
      if (pollId != null) window.clearInterval(pollId)
    }
  }, [brandId])

  useEffect(() => {
    if (!brandId || !hasMore || nextOffset == null) return
    const node = loadMoreRef.current
    if (!node) return

    let cancelled = false
    let requestInFlight = false

    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0]
        if (!entry?.isIntersecting || requestInFlight) return
        requestInFlight = true
        setLoadingMore(true)
        void listJobs(brandId, {
          offset: nextOffset,
          limit: EXECUTIONS_PAGE_SIZE,
        })
          .then((response) => {
            if (cancelled) return
            setItems((current) => {
              const seen = new Set(current.map((item) => item.external_id))
              const appended = response.items.filter((item) => !seen.has(item.external_id))
              return [...current, ...appended]
            })
            setNextOffset(response.next_offset)
            setHasMore(response.has_more)
          })
          .catch(() => {
            if (cancelled) return
            setError("Couldn't load more executions. Scroll again to retry.")
          })
          .finally(() => {
            requestInFlight = false
            if (!cancelled) setLoadingMore(false)
          })
      },
      { rootMargin: '240px 0px' },
    )

    observer.observe(node)
    return () => {
      cancelled = true
      observer.disconnect()
    }
  }, [brandId, hasMore, nextOffset])

  if (!brand) {
    return <Navigate to="/brands" replace />
  }

  const filtered = debouncedQuery
    ? items.filter((item) => {
        const haystack = [
          `execution ${item.execution_number}`,
          item.status,
          statusLabel(item.status),
          skuProgressLabel(item),
          item.marketplace_name ?? '',
          item.marketplaces.map((marketplace) => marketplace.name).join(' '),
          item.created_by_name ?? '',
          item.category_name ?? '',
        ]
          .join(' ')
          .toLowerCase()
        return haystack.includes(debouncedQuery)
      })
    : items
  const sections = groupByDay(filtered)
  const showList = !loading && items.length > 0
  const live = hasInProgressJobs(items)

  return (
    <div className="page-shell">
      <AppHeader brandName={brand.name} />
      <main className={showList ? 'executions-page' : 'workspace-page'}>
        {loading ? (
          <p className="executions-page__status">Loading executions…</p>
        ) : null}

        {!loading && error ? <p className="executions-page__error">{error}</p> : null}

        {!loading && !error && items.length === 0 ? (
          <div className="workspace-empty">
            <h1 className="workspace-empty__title">Nothing here yet.</h1>
            <p className="workspace-empty__body">
              Start by uploading a product file and a folder of images. Everything else follows from
              there — and the batch stays yours to edit afterwards.
            </p>
            <button
              type="button"
              className="btn-primary"
              onClick={() => navigate('/workspace/new')}
            >
              <PlusIcon />
              New batch
            </button>
          </div>
        ) : null}

        {showList ? (
          <div className="executions-page__inner">
            <div className="executions-page__toolbar">
              <div className="executions-page__title-block">
                <h1 className="executions-page__title">Executions</h1>
                <span
                  className={
                    refreshing || live
                      ? 'executions-page__live executions-page__live--active'
                      : 'executions-page__live'
                  }
                  aria-live="polite"
                >
                  <span
                    className={
                      refreshing
                        ? 'executions-page__live-dot executions-page__live-dot--fetching'
                        : 'executions-page__live-dot'
                    }
                  />
                  {refreshing ? 'Updating…' : live ? 'Live' : 'Up to date'}
                </span>
              </div>
              <div className="executions-page__actions">
                <label className="executions-page__search">
                  <SearchIcon />
                  <input
                    type="search"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Search executions"
                    aria-label="Search executions"
                  />
                </label>
                <button
                  type="button"
                  className="btn-primary executions-page__new"
                  onClick={() => navigate('/workspace/new')}
                >
                  <PlusIcon />
                  New batch
                </button>
              </div>
            </div>

            {filtered.length === 0 ? (
              <p className="executions-page__status">No executions match your search.</p>
            ) : (
              <>
                {sections.map((section) => (
                  <section key={section.key} className="executions-section">
                    <h2 className="executions-section__label">{section.label}</h2>
                    <ul className="executions-section__list">
                      {section.items.map((item) => (
                        <li key={item.external_id}>
                          <article className="execution-card">
                            <div className="execution-card__main">
                              <StatusIcon status={item.status} />
                              <div className="execution-card__copy">
                                <p className="execution-card__title">
                                  Execution {item.execution_number}
                                  <span className="execution-card__date">
                                    · {formatShortDateTime(item.started_at)}
                                  </span>
                                </p>
                                <p className="execution-card__meta">
                                  <span>{skuProgressLabel(item)}</span>
                                  {item.created_by_name ? (
                                    <span className="execution-card__ran-by">
                                      Ran by {item.created_by_name}
                                    </span>
                                  ) : null}
                                </p>
                              </div>
                            </div>
                            <div className="execution-card__side">
                              <span
                                className={
                                  item.status === 'COMPLETED'
                                    ? 'execution-card__status execution-card__status--done'
                                    : item.status === 'FAILED'
                                      ? 'execution-card__status execution-card__status--failed'
                                      : 'execution-card__status execution-card__status--pending'
                                }
                              >
                                {statusLabel(item.status)}
                              </span>
                              <button
                                type="button"
                                className="btn-outline execution-card__open"
                                onClick={() => navigate(`/batches/preview/${item.external_id}`)}
                              >
                                Open
                              </button>
                            </div>
                          </article>
                        </li>
                      ))}
                    </ul>
                  </section>
                ))}
                {loadingMore ? (
                  <p className="executions-page__status">Loading more executions…</p>
                ) : null}
                {hasMore ? <div ref={loadMoreRef} className="executions-page__sentinel" /> : null}
              </>
            )}
          </div>
        ) : null}
      </main>
    </div>
  )
}

export default Workspace
