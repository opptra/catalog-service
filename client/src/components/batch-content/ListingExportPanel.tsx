import { useState } from 'react'
import axios from 'axios'
import {
  fillListing,
  type FillListingResponse,
  type ListingFillGap,
} from '../../api/listing'

interface ListingExportPanelProps {
  jobExternalId: string
  /** When false, show a locked hint (generation still running). */
  enabled: boolean
}

function formatFillError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (error.message) return error.message
  }
  if (error instanceof Error && error.message) return error.message
  return 'Could not fill the listing file. Please try again.'
}

function groupGapsBySku(gaps: ListingFillGap[]): Array<{ skuId: string; items: ListingFillGap[] }> {
  const map = new Map<string, ListingFillGap[]>()
  for (const gap of gaps) {
    const existing = map.get(gap.sku_id)
    if (existing) existing.push(gap)
    else map.set(gap.sku_id, [gap])
  }
  return [...map.entries()].map(([skuId, items]) => ({ skuId, items }))
}

function ListingExportPanel({ jobExternalId, enabled }: ListingExportPanelProps) {
  const [filling, setFilling] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<FillListingResponse | null>(null)
  const [gapsOpen, setGapsOpen] = useState(false)

  async function handleFill() {
    if (!enabled || filling) return
    setFilling(true)
    setError(null)
    try {
      const next = await fillListing(jobExternalId)
      setResult(next)
      setGapsOpen(next.gaps.length > 0)
      if (next.filled_file_url) {
        window.open(next.filled_file_url, '_blank', 'noopener,noreferrer')
      }
    } catch (err) {
      setError(formatFillError(err))
    } finally {
      setFilling(false)
    }
  }

  const gapGroups = result ? groupGapsBySku(result.gaps) : []

  return (
    <section className="listing-export" aria-label="Listing file export">
      <div className="listing-export__row">
        <div className="listing-export__copy">
          <p className="listing-export__eyebrow">Listing file</p>
          <p className="listing-export__title">
            {enabled
              ? 'Download the filled Amazon listing workbook'
              : 'Available when generation completes'}
          </p>
          <p className="listing-export__hint">
            {enabled
              ? filling
                ? 'Filling template columns from this job (images via Dropbox, enums, mapped fields)…'
                : 'Uses generated content from this job. Empty required cells are reported as gaps.'
              : 'Finish SKU generation first, then export the marketplace listing file.'}
          </p>
        </div>
        <button
          type="button"
          className="btn-primary batch-content__export"
          disabled={!enabled || filling}
          onClick={() => void handleFill()}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 16 16"
            fill="none"
            aria-hidden="true"
          >
            <path
              d="M8 2v8.5M8 10.5 5 7.5M8 10.5 11 7.5M3 13.5h10"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          {filling ? 'Filling listing…' : result ? 'Download again' : 'Download listing file'}
        </button>
      </div>

      {filling ? (
        <div className="listing-export__progress" role="status" aria-live="polite">
          <div className="pipeline-progress__track">
            <div className="pipeline-progress__fill pipeline-progress__fill--indeterminate" />
          </div>
          <p className="listing-export__progress-label">Fill in progress — this can take a minute</p>
        </div>
      ) : null}

      {error ? <p className="batch-content__error">{error}</p> : null}

      {result && !filling ? (
        <div className="listing-export__result">
          <p className="listing-export__result-meta">
            {result.gaps.length === 0
              ? 'Listing file ready — no gaps reported.'
              : `${result.gaps.length} gap${result.gaps.length === 1 ? '' : 's'} across ${gapGroups.length} SKU${gapGroups.length === 1 ? '' : 's'}.`}
            {result.filled_file_url ? (
              <>
                {' '}
                <a
                  className="listing-export__link"
                  href={result.filled_file_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Open file
                </a>
              </>
            ) : null}
          </p>
          {result.gaps.length > 0 ? (
            <div className="listing-export__gaps">
              <button
                type="button"
                className="listing-export__gaps-toggle"
                onClick={() => setGapsOpen((open) => !open)}
                aria-expanded={gapsOpen}
              >
                {gapsOpen ? 'Hide gaps' : 'Show gaps'}
              </button>
              {gapsOpen ? (
                <ul className="listing-export__gap-list">
                  {gapGroups.map((group) => (
                    <li key={group.skuId} className="listing-export__gap-sku">
                      <p className="listing-export__gap-sku-id">{group.skuId}</p>
                      <ul>
                        {group.items.map((gap) => (
                          <li key={`${gap.sku_id}-${gap.column_label}-${gap.reason}`}>
                            <span className="listing-export__gap-col">{gap.column_label}</span>
                            <span className="listing-export__gap-reason">{gap.reason}</span>
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}

export default ListingExportPanel
