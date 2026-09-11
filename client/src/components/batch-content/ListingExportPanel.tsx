import { useEffect, useId, useState } from 'react'
import axios from 'axios'
import {
  fillListing,
  getJobGroupListingFiles,
  type JobGroupListingFileItem,
  type ListingFillGap,
  type StartListingFillResponse,
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
  return 'Could not start the listing fill. Please try again.'
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

function formatGeneratedAt(value: string | null): string {
  if (!value) return 'Not generated yet'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
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

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      className={
        open
          ? 'listing-export__file-chevron listing-export__file-chevron--open'
          : 'listing-export__file-chevron'
      }
      width="18"
      height="18"
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M6 3.5 10.5 8 6 12.5"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
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
          Start filling the listing workbook for one marketplace in this batch. Refresh the page
          when it finishes to download the latest file.
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
            {confirming ? 'Starting…' : 'Start listing fill'}
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
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ack, setAck] = useState<StartListingFillResponse | null>(null)
  const [files, setFiles] = useState<JobGroupListingFileItem[]>([])
  const [filesError, setFilesError] = useState<string | null>(null)
  const [filesLoading, setFilesLoading] = useState(false)
  const [filesSectionOpen, setFilesSectionOpen] = useState(false)
  const [gapsOpenByMarketplace, setGapsOpenByMarketplace] = useState<Record<string, boolean>>({})

  useEffect(() => {
    if (!pickerOpen) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && !starting) setPickerOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [pickerOpen, starting])

  useEffect(() => {
    let cancelled = false
    async function loadFiles() {
      setFilesLoading(true)
      try {
        const next = await getJobGroupListingFiles(jobGroupId)
        if (cancelled) return
        setFiles(next.files)
        setFilesError(null)
      } catch (err) {
        if (cancelled) return
        setFilesError(formatFillError(err))
      } finally {
        if (!cancelled) setFilesLoading(false)
      }
    }
    void loadFiles()
    return () => {
      cancelled = true
    }
  }, [jobGroupId])

  function openPicker() {
    if (!enabled || starting || marketplaces.length === 0) return
    setError(null)
    setPickedId(defaultMarketplaceId(marketplaces, preferredMarketplaceExternalId))
    setPickerOpen(true)
  }

  function closePicker() {
    if (starting) return
    setPickerOpen(false)
  }

  async function handleConfirm() {
    const marketplace = marketplaces.find((item) => item.marketplace_external_id === pickedId)
    if (!marketplace || starting) return
    setStarting(true)
    setError(null)
    try {
      const next = await fillListing({
        job_group_id: jobGroupId,
        marketplace_external_id: marketplace.marketplace_external_id,
      })
      setAck(next)
      setPickerOpen(false)
    } catch (err) {
      setError(formatFillError(err))
    } finally {
      setStarting(false)
    }
  }

  return (
    <section className="listing-export" aria-label="Listing file export">
      <div className="listing-export__row">
        <div className="listing-export__copy">
          <p className="listing-export__eyebrow">Listing file</p>
          <p className="listing-export__title">Download the filled listing workbook</p>
          <p className="listing-export__hint">
            {enabled
              ? 'Choose a marketplace to start filling. When it finishes, refresh this page to see the latest marketplace file below.'
              : 'Finish SKU generation first, then export a marketplace listing file.'}
          </p>
        </div>
        <button
          type="button"
          className="btn-primary batch-content__export"
          disabled={!enabled || starting || marketplaces.length === 0}
          onClick={openPicker}
        >
          <DownloadIcon />
          {starting ? 'Starting…' : 'Download listing file'}
        </button>
      </div>

      {ack ? (
        <div className="listing-export__progress" role="status" aria-live="polite">
          <p className="listing-export__progress-label">{ack.message}</p>
        </div>
      ) : null}

      {error && !pickerOpen ? <p className="batch-content__error">{error}</p> : null}

      <div className="listing-export__files">
        <button
          type="button"
          className="listing-export__files-toggle"
          aria-expanded={filesSectionOpen}
          onClick={() => setFilesSectionOpen((open) => !open)}
        >
          <span className="listing-export__files-title">Marketplace files</span>
          <ChevronIcon open={filesSectionOpen} />
        </button>
        <div
          className={
            filesSectionOpen
              ? 'listing-export__files-panel listing-export__files-panel--open'
              : 'listing-export__files-panel'
          }
        >
          <div className="listing-export__files-panel-inner">
            <div className="listing-export__files-body">
              {filesLoading ? (
                <p className="listing-export__files-hint">Loading latest files…</p>
              ) : null}
              {filesError ? <p className="batch-content__error">{filesError}</p> : null}
              {!filesLoading && !filesError && files.length === 0 ? (
                <p className="listing-export__files-hint">No marketplace files yet.</p>
              ) : null}
              <ul className="listing-export__file-list">
                {files.map((file) => {
                  const gapGroups = groupGapsBySku(file.gaps)
                  const gapsOpen = gapsOpenByMarketplace[file.marketplace_external_id] === true
                  return (
                    <li key={file.job_external_id} className="listing-export__file-item">
                      <div className="listing-export__file-head">
                        <div className="listing-export__file-copy">
                          <p className="listing-export__file-name">{file.marketplace_name}</p>
                          {file.filled_file_url && file.generated_at ? (
                            <p className="listing-export__file-generated">
                              <span className="listing-export__file-generated-label">
                                Latest generated
                              </span>
                              <span className="listing-export__file-generated-value">
                                {formatGeneratedAt(file.generated_at)}
                              </span>
                            </p>
                          ) : (
                            <p className="listing-export__file-meta">No file generated yet</p>
                          )}
                        </div>
                        {file.filled_file_url ? (
                          <a
                            className="listing-export__link listing-export__link--file"
                            href={file.filled_file_url}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            Open file
                          </a>
                        ) : null}
                      </div>
                      {file.gaps.length > 0 ? (
                        <div className="listing-export__gaps">
                          <button
                            type="button"
                            className="listing-export__gaps-toggle"
                            onClick={() =>
                              setGapsOpenByMarketplace((prev) => ({
                                ...prev,
                                [file.marketplace_external_id]: !gapsOpen,
                              }))
                            }
                            aria-expanded={gapsOpen}
                          >
                            {gapsOpen
                              ? 'Hide gaps'
                              : `Show ${file.gaps.length} gap${file.gaps.length === 1 ? '' : 's'}`}
                          </button>
                          {gapsOpen ? (
                            <ul className="listing-export__gap-list">
                              {gapGroups.map((group) => (
                                <li key={group.skuId} className="listing-export__gap-sku">
                                  <p className="listing-export__gap-sku-id">{group.skuId}</p>
                                  <ul>
                                    {group.items.map((gap) => (
                                      <li key={`${gap.sku_id}-${gap.column_label}-${gap.reason}`}>
                                        <span className="listing-export__gap-col">
                                          {gap.column_label}
                                        </span>
                                        <span className="listing-export__gap-reason">
                                          {gap.message || gap.reason}
                                        </span>
                                        {gap.message ? (
                                          <span className="listing-export__gap-code">
                                            {gap.reason}
                                          </span>
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
                    </li>
                  )
                })}
              </ul>
            </div>
          </div>
        </div>
      </div>

      <MarketplacePickerModal
        open={pickerOpen}
        marketplaces={marketplaces}
        selectedId={pickedId}
        confirming={starting}
        error={error}
        onSelect={setPickedId}
        onCancel={closePicker}
        onConfirm={() => void handleConfirm()}
      />
    </section>
  )
}

export default ListingExportPanel
