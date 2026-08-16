import { useEffect, useState } from 'react'
import axios from 'axios'
import {
  regenerateAttributeValue,
  restoreAttributeValue,
  type RegenerateAttributeValueResponse,
} from '../../api/jobs'

export type RegenDataType = 'IMAGE' | 'TEXT'

export interface AttributeRegenTarget {
  dataType: RegenDataType
  label: string
  headerLabel: string
  valueExternalId: string
  version: number
  /** Signed image URL or text content. */
  value: string
  /** Optional nav for image carousels. */
  canPrev?: boolean
  canNext?: boolean
  onPrev?: () => void
  onNext?: () => void
}

interface AttributeRegenModalProps {
  open: boolean
  target: AttributeRegenTarget | null
  onClose: () => void
  /** Called after a successful use-new or keep-previous so the page can refresh content. */
  onApplied: () => void
}

type Phase = 'edit' | 'loading' | 'compare'

interface Snapshot {
  version: number
  value: string
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

function RefreshIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M13.5 2.5v3.5h-3.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M13.2 6A5.5 5.5 0 1 0 12.4 11.2"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function parseBulletList(raw: string): string[] {
  try {
    const parsed: unknown = JSON.parse(raw)
    if (Array.isArray(parsed)) {
      return parsed.filter((item): item is string => typeof item === 'string')
    }
  } catch {
    // fall through
  }
  return raw
    .split(/\n|•/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function errorMessage(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (Array.isArray(detail)) {
      const first = detail.find(
        (item): item is { msg?: string } =>
          typeof item === 'object' && item != null && 'msg' in item,
      )
      if (typeof first?.msg === 'string' && first.msg.trim()) return first.msg
    }
    if (typeof err.message === 'string' && err.message.trim()) return err.message
  }
  if (err instanceof Error && err.message.trim()) return err.message
  return fallback
}

function TextPreview({
  label,
  value,
  badge,
  emphasize,
}: {
  label: string
  value: string
  badge?: string
  emphasize?: boolean
}) {
  const looksLikeBullets =
    value.trimStart().startsWith('[') || value.includes('•') || value.includes('\n')
  const bullets = looksLikeBullets ? parseBulletList(value) : []
  const useList = bullets.length > 1

  return (
    <div className={`attr-regen__panel${emphasize ? ' attr-regen__panel--new' : ''}`}>
      <div className="attr-regen__panel-head">
        <p className="attr-regen__panel-label">{label}</p>
        {badge ? (
          <span className={`attr-regen__badge${emphasize ? ' attr-regen__badge--new' : ''}`}>
            {badge}
          </span>
        ) : null}
      </div>
      <div className="attr-regen__text">
        {useList ? (
          <ul className="attr-regen__bullets">
            {bullets.map((item, index) => (
              <li key={`${index}-${item.slice(0, 24)}`}>{item}</li>
            ))}
          </ul>
        ) : (
          <p className="attr-regen__text-body">{value || '—'}</p>
        )}
      </div>
    </div>
  )
}

function ImagePreview({
  label,
  url,
  badge,
  emphasize,
}: {
  label: string
  url: string
  badge: string
  emphasize?: boolean
}) {
  return (
    <div className={`attr-regen__panel${emphasize ? ' attr-regen__panel--new' : ''}`}>
      <div className="attr-regen__panel-head">
        <p className="attr-regen__panel-label">{label}</p>
        <span className={`attr-regen__badge${emphasize ? ' attr-regen__badge--new' : ''}`}>
          {badge}
        </span>
      </div>
      <div className="attr-regen__image">
        <img src={url} alt={label} />
      </div>
    </div>
  )
}

function AttributeRegenModal({ open, target, onClose, onApplied }: AttributeRegenModalProps) {
  const [phase, setPhase] = useState<Phase>('edit')
  const [improvement, setImprovement] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [previous, setPrevious] = useState<Snapshot | null>(null)
  const [generated, setGenerated] = useState<RegenerateAttributeValueResponse | null>(null)
  const [choosing, setChoosing] = useState(false)

  useEffect(() => {
    if (!open) return
    setPhase('edit')
    setImprovement('')
    setError(null)
    setPrevious(null)
    setGenerated(null)
    setChoosing(false)
  }, [open, target?.valueExternalId])

  useEffect(() => {
    if (!open) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && phase !== 'loading' && !choosing) {
        if (phase === 'compare') onApplied()
        onClose()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, phase, choosing, onApplied, onClose])

  function handleDismiss() {
    // New version is already latest after regenerate; refresh if user leaves compare.
    if (phase === 'compare') onApplied()
    onClose()
  }

  if (!open || target == null) return null

  async function handleRegenerate() {
    const note = improvement.trim()
    if (!note || target == null) return
    setError(null)
    setPhase('loading')
    setPrevious({ version: target.version, value: target.value })
    try {
      const next = await regenerateAttributeValue(target.valueExternalId, {
        improvement: note,
      })
      setGenerated(next)
      setPhase('compare')
    } catch (err) {
      setError(errorMessage(err, 'Regeneration failed.'))
      setPhase('edit')
      setPrevious(null)
    }
  }

  function handleUseNew() {
    setChoosing(false)
    onApplied()
    onClose()
  }

  async function handleKeepPrevious() {
    if (target == null || previous == null) return
    setChoosing(true)
    setError(null)
    try {
      await restoreAttributeValue(target.valueExternalId, { version: previous.version })
      onApplied()
      onClose()
    } catch (err) {
      setError(errorMessage(err, 'Could not keep the previous version.'))
      setChoosing(false)
    }
  }

  const isImage = target.dataType === 'IMAGE'
  const dialogWide = phase === 'compare'

  return (
    <div className="img-modal" role="presentation">
      <button
        type="button"
        className="img-modal__backdrop"
        aria-label="Close"
        onClick={() => {
          if (phase !== 'loading' && !choosing) handleDismiss()
        }}
      />
      <div
        className={`img-modal__dialog${dialogWide ? ' img-modal__dialog--wide' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={target.headerLabel}
      >
        <div className="img-modal__header">
          <p className="img-modal__context">{target.headerLabel}</p>
          <button
            type="button"
            className="img-modal__close"
            onClick={handleDismiss}
            aria-label="Close"
            disabled={phase === 'loading' || choosing}
          >
            <CloseIcon />
          </button>
        </div>

        {phase === 'edit' || phase === 'loading' ? (
          <>
            {isImage ? (
              <div className="img-modal__preview">
                <img src={target.value} alt={target.label} />
              </div>
            ) : (
              <TextPreview label={target.label} value={target.value} />
            )}

            <div className="img-modal__prompt-row">
              <input
                type="text"
                className="img-modal__prompt"
                value={improvement}
                onChange={(event) => setImprovement(event.target.value)}
                placeholder={
                  isImage
                    ? 'describe what to change: “make the pillow navy”'
                    : 'describe what to change: “shorter, more benefit-led”'
                }
                disabled={phase === 'loading'}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    void handleRegenerate()
                  }
                }}
              />
              <button
                type="button"
                className="img-modal__regen"
                onClick={() => void handleRegenerate()}
                aria-label="Regenerate"
                title="Regenerate"
                disabled={phase === 'loading' || improvement.trim().length === 0}
              >
                <RefreshIcon />
              </button>
            </div>
            {isImage ? (
              <p className="attr-regen__hint">
                Only the requested change should move; everything else stays as-is.
              </p>
            ) : null}

            {phase === 'loading' ? (
              <p className="attr-regen__status">Generating a new version…</p>
            ) : null}
            {error ? <p className="attr-regen__error">{error}</p> : null}

            {isImage ? (
              <div className="img-modal__footer">
                <button
                  type="button"
                  className="img-modal__nav"
                  onClick={target.onPrev}
                  disabled={!target.canPrev || phase === 'loading'}
                >
                  ← prev image
                </button>
                <button
                  type="button"
                  className="img-modal__nav"
                  onClick={target.onNext}
                  disabled={!target.canNext || phase === 'loading'}
                >
                  next image →
                </button>
              </div>
            ) : null}
          </>
        ) : null}

        {phase === 'compare' && previous != null && generated != null ? (
          <>
            <p className="attr-regen__compare-lede">
              Side-by-side comparison. Choose which version should stay as current.
            </p>
            <div className={`attr-regen__compare${isImage ? '' : ' attr-regen__compare--text'}`}>
              {isImage ? (
                <>
                  <ImagePreview
                    label="Previous"
                    url={previous.value}
                    badge={`v${previous.version}`}
                  />
                  <ImagePreview
                    label="Newly generated"
                    url={generated.value}
                    badge={`v${generated.version} · new`}
                    emphasize
                  />
                </>
              ) : (
                <>
                  <TextPreview
                    label="Previous"
                    value={previous.value}
                    badge={`v${previous.version}`}
                  />
                  <TextPreview
                    label="Newly generated"
                    value={generated.value}
                    badge={`v${generated.version} · new`}
                    emphasize
                  />
                </>
              )}
            </div>

            {error ? <p className="attr-regen__error">{error}</p> : null}
            {choosing ? (
              <p className="attr-regen__status">Restoring previous version as latest…</p>
            ) : null}

            <div className="attr-regen__actions">
              <button
                type="button"
                className="btn-outline"
                onClick={() => void handleKeepPrevious()}
                disabled={choosing}
              >
                Keep previous
              </button>
              <button
                type="button"
                className="btn-primary"
                onClick={handleUseNew}
                disabled={choosing}
              >
                Use new
              </button>
            </div>
          </>
        ) : null}
      </div>
    </div>
  )
}

export default AttributeRegenModal
