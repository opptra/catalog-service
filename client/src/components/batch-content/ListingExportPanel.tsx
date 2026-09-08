import { useEffect, useId, useState } from 'react'
import axios from 'axios'
import {
  fillListing,
  type FillListingResponse,
  type ListingFillGap,
} from '../../api/listing'

export interface ListingExportMarketplace {
  marketplace_external_id: string
  marketplace_name: string
}

interface ListingExportPanelProps {
  jobGroupId: string
  marketplaces: ListingExportMarketplace[]
  /** Pre-select this marketplace in the picker when the banner is opened. */
  preferredMarketplaceExternalId?: string | null
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

function CloseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M4 4L12 12M12 4L4 12"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  )
}

function DownloadIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M8 2v8.5M8 10.5 5 7.5M8 10.5 11 7.5M3 13.5h10"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function defaultMarketplaceId(
  marketplaces: ListingExportMarketplace[],
  preferred: string | null | undefined,
): string {
  if (
    preferred &&
    marketplaces.some((item) => item.marketplace_external_id === preferred)
  ) {
    return preferred
  }
  return marketplaces[0]?.marketplace_external_id ?? ''
}

function MarketplacePickerModal({
  open,
  marketplaces,
  selectedId,
  confirming,
  error,
  onSelect,
  onCancel,
  onConfirm,
}: {
  open: boolean
  marketplaces: ListingExportMarketplace[]
  selectedId: string
  confirming: boolean
  error: string | null
  onSelect: (marketplaceExternalId: string) => void
  onCancel: () => void
  onConfirm: () => void
}) {
  const titleId = useId()

  if (!open) return null

  return (
    <div className="img-modal" role="presentation">
      <button
        type="button"
        className="img-modal__backdrop"
        aria-label="Close marketplace picker"
        onClick={onCancel}
      />
      <div
        className="img-modal__dialog listing-export-picker"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <div className="img-modal__header">
          <p id={titleId} className="img-modal__context">
            Select a marketplace
          </p>
          <button type="button" className="img-modal__close" onClick={onCancel} aria-label="Close">
            <CloseIcon />
          </button>
        </div>
        <p className="listing-export-picker__lede">
          Download the filled listing workbook for one marketplace in this batch.
        </p>
        <div className="listing-export-picker__list" role="radiogroup" aria-label="Marketplaces">
          {marketplaces.map((marketplace) => {
            const selected = marketplace.marketplace_external_id === selectedId
            return (
              <button
                key={marketplace.marketplace_external_id}
                type="button"
                role="radio"
                aria-checked={selected}
                className={
                  selected
                    ? 'listing-export-picker__option listing-export-picker__option--on'
                    : 'listing-export-picker__option'
                }
                onClick={() => onSelect(marketplace.marketplace_external_id)}
              >
                <span className={selected ? 'check check--on' : 'check'} aria-hidden="true" />
                <span className="listing-export-picker__name">{marketplace.marketplace_name}</span>
              </button>
            )
          })}
        </div>
        {error ? <p className="listing-export-picker__error">{error}</p> : null}
        <div className="listing-export-picker__actions">
          <button type="button" className="btn-outline" onClick={onCancel} disabled={confirming}>
            Cancel
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={onConfirm}
            disabled={!selectedId || confirming}
          >
            {confirming ? 'Filling listing…' : 'Download listing file'}
          </button>
        </div>
      </div>
    </div>
  )
}

function ListingExportPanel({
  jobGroupId,
  marketplaces,
  preferredMarketplaceExternalId,
  enabled,
}: ListingExportPanelProps) {
  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickedId, setPickedId] = useState('')
  const [filling, setFilling] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<FillListingResponse | null>(null)
  const [resultMarketplaceName, setResultMarketplaceName] = useState<string | null>(null)
  const [gapsOpen, setGapsOpen] = useState(false)

  useEffect(() => {
    if (!pickerOpen) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && !filling) setPickerOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [pickerOpen, filling])

  function openPicker() {
    if (!enabled || filling || marketplaces.length === 0) return
    setError(null)
    setPickedId(defaultMarketplaceId(marketplaces, preferredMarketplaceExternalId))
    setPickerOpen(true)
  }

  function closePicker() {
    if (filling) return
    setPickerOpen(false)
  }

  async function handleConfirm() {
    const marketplace = marketplaces.find((item) => item.marketplace_external_id === pickedId)
    if (!marketplace || filling) return
    setFilling(true)
    setError(null)
    try {
      const next = await fillListing({
        job_group_id: jobGroupId,
        marketplace_external_id: marketplace.marketplace_external_id,
      })
      setResult(next)
      setResultMarketplaceName(marketplace.marketplace_name)
      setGapsOpen(next.gaps.length > 0)
      setPickerOpen(false)
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
          <p className="listing-export__title">Download the filled listing workbook</p>
          <p className="listing-export__hint">
            {enabled
              ? filling
                ? 'Filling template columns from this job (images via Dropbox, enums, mapped fields)…'
                : 'Choose a marketplace, then we fill that listing file from this job. Empty required cells are reported as gaps.'
              : 'Finish SKU generation first, then export a marketplace listing file.'}
          </p>
        </div>
        <button
          type="button"
          className="btn-primary batch-content__export"
          disabled={!enabled || filling || marketplaces.length === 0}
          onClick={openPicker}
        >
          <DownloadIcon />
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

      {error && !pickerOpen ? <p className="batch-content__error">{error}</p> : null}

      {result && !filling ? (
        <div className="listing-export__result">
          <p className="listing-export__result-meta">
            {result.gaps.length === 0
              ? `${resultMarketplaceName ?? 'Listing'} file ready — no gaps reported.`
              : `${result.gaps.length} gap${result.gaps.length === 1 ? '' : 's'} across ${gapGroups.length} SKU${gapGroups.length === 1 ? '' : 's'}${resultMarketplaceName ? ` (${resultMarketplaceName})` : ''}.`}
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
                            <span className="listing-export__gap-reason">
                              {gap.message || gap.reason}
                            </span>
                            {gap.message ? (
                              <span className="listing-export__gap-code">{gap.reason}</span>
                            ) : null}
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

      <MarketplacePickerModal
        open={pickerOpen}
        marketplaces={marketplaces}
        selectedId={pickedId}
        confirming={filling}
        error={error}
        onSelect={setPickedId}
        onCancel={closePicker}
        onConfirm={() => void handleConfirm()}
      />
    </section>
  )
}

export default ListingExportPanel
