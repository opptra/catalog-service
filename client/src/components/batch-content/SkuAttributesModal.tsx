import { useEffect, useState } from 'react'
import axios from 'axios'
import { getSkuAttributes, type SkuAttributeItem } from '../../api/jobs'

interface SkuAttributesModalProps {
  open: boolean
  skuGenerationJobExternalId: string | null
  skuLabel: string
  onClose: () => void
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
        d="M8 2.5V10.5M8 10.5L5 7.5M8 10.5L11 7.5M3 13.5H13"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function formatLoadError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (error.message) return error.message
  }
  if (error instanceof Error && error.message) return error.message
  return 'Could not load attributes.'
}

interface HighlightPart {
  value: string
  matched: boolean
}

function splitHighlightParts(text: string, needle: string): HighlightPart[] {
  const lowerText = text.toLowerCase()
  const lowerNeedle = needle.toLowerCase()
  const parts: HighlightPart[] = []
  let start = 0
  let index = lowerText.indexOf(lowerNeedle, start)
  while (index !== -1) {
    if (index > start) {
      parts.push({ value: text.slice(start, index), matched: false })
    }
    parts.push({ value: text.slice(index, index + needle.length), matched: true })
    start = index + needle.length
    index = lowerText.indexOf(lowerNeedle, start)
  }
  if (start < text.length) {
    parts.push({ value: text.slice(start), matched: false })
  }
  return parts
}

function HighlightedText({ text, query }: { text: string; query: string }) {
  const needle = query.trim()
  if (!needle) return text

  return splitHighlightParts(text, needle).map((part, index) =>
    part.matched ? (
      <mark key={index} className="sku-attributes-modal__mark">
        {part.value}
      </mark>
    ) : (
      <span key={index}>{part.value}</span>
    ),
  )
}

function SkuAttributesModal({
  open,
  skuGenerationJobExternalId,
  skuLabel,
  onClose,
}: SkuAttributesModalProps) {
  const [skuId, setSkuId] = useState('')
  const [attributes, setAttributes] = useState<SkuAttributeItem[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || skuGenerationJobExternalId == null) return

    let cancelled = false
    setSkuId('')
    setAttributes([])
    setQuery('')
    setError(null)
    setExportError(null)
    setLoading(true)

    void getSkuAttributes(skuGenerationJobExternalId)
      .then((data) => {
        if (cancelled) return
        setSkuId(data.sku_id)
        setAttributes(data.attributes)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(formatLoadError(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [open, skuGenerationJobExternalId])

  useEffect(() => {
    if (!open) return

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }

    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  const needle = query.trim().toLowerCase()
  const visible = needle
    ? attributes.filter(
        (item) =>
          item.name.toLowerCase().includes(needle) ||
          item.value.toLowerCase().includes(needle),
      )
    : attributes
  const canExport = !loading && error == null && attributes.length > 0 && !exporting

  function handleExportCsv() {
    if (!canExport) return
    setExportError(null)
    setExporting(true)
    void import('../../lib/downloadSkuAttributesCsv')
      .then(({ downloadSkuAttributesCsv }) => {
        downloadSkuAttributesCsv(skuId || skuLabel, attributes)
      })
      .catch((err: unknown) => {
        setExportError(err instanceof Error && err.message ? err.message : 'Could not export CSV.')
      })
      .finally(() => {
        setExporting(false)
      })
  }

  if (!open) return null

  return (
    <div className="img-modal" role="presentation">
      <button
        type="button"
        className="img-modal__backdrop"
        aria-label="Close"
        onClick={onClose}
      />
      <div
        className="img-modal__dialog sku-attributes-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`Input attributes · ${skuLabel}`}
      >
        <div className="img-modal__header">
          <p className="img-modal__context">
            Input attributes · {skuLabel}
            {!loading && error == null
              ? needle
                ? ` · ${visible.length} of ${attributes.length}`
                : ` · ${attributes.length}`
              : ''}
          </p>
          <div className="img-modal__header-actions">
            <button
              type="button"
              className="img-modal__export"
              onClick={handleExportCsv}
              disabled={!canExport}
            >
              <DownloadIcon />
              {exporting ? 'Exporting…' : 'Export as CSV'}
            </button>
            <button type="button" className="img-modal__close" onClick={onClose} aria-label="Close">
              <CloseIcon />
            </button>
          </div>
        </div>

        {exportError != null ? (
          <p className="sku-attributes-modal__export-error">{exportError}</p>
        ) : null}

        {!loading && error == null && attributes.length > 0 ? (
          <label className="sku-attributes-modal__search">
            <span className="visually-hidden">Filter attributes</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Filter by name or value"
              autoComplete="off"
            />
          </label>
        ) : null}

        <div className="sku-attributes-modal__body">
          {loading ? (
            <div
              className="sku-attributes-modal__shimmer content-shimmer"
              aria-busy="true"
              aria-label="Loading attributes"
            />
          ) : error != null ? (
            <p className="sku-attributes-modal__empty sku-attributes-modal__empty--error">
              {error}
            </p>
          ) : attributes.length === 0 ? (
            <p className="sku-attributes-modal__empty">No filled attributes for this SKU.</p>
          ) : visible.length === 0 ? (
            <p className="sku-attributes-modal__empty">No attributes match that filter.</p>
          ) : (
            <dl className="sku-attributes-modal__list">
              {visible.map((item) => (
                <div key={item.name} className="sku-attributes-modal__row">
                  <dt>
                    <HighlightedText text={item.name} query={query} />
                  </dt>
                  <dd>
                    <HighlightedText text={item.value} query={query} />
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </div>
    </div>
  )
}

export default SkuAttributesModal
