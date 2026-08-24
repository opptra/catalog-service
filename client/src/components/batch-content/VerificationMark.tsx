import { useCallback, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import type { ImageVerification, ImageVerificationSnapshot } from '../../api/jobs'
import {
  isVerificationBelowThreshold,
  verificationAxisLines,
  verificationCardTitle,
  verificationMismatchLines,
  verificationOutcomeLine,
  verificationPercentLabel,
} from '../../batch/imageVerification'

function PassCircleIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
      <circle cx="7" cy="7" r="7" fill="currentColor" />
      <path
        d="M4.15 7.2 6.1 9.1 9.9 4.95"
        fill="none"
        stroke="#fff"
        strokeWidth="1.55"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function FailCircleIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
      <circle cx="7" cy="7" r="7" fill="currentColor" />
      <path
        d="M5 5l4 4M9 5l-4 4"
        fill="none"
        stroke="#fff"
        strokeWidth="1.55"
        strokeLinecap="round"
      />
    </svg>
  )
}

function WarnCircleIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
      <circle cx="7" cy="7" r="7" fill="currentColor" />
      <path
        d="M7 4.2v3.4"
        fill="none"
        stroke="#fff"
        strokeWidth="1.55"
        strokeLinecap="round"
      />
      <circle cx="7" cy="9.7" r="0.7" fill="#fff" />
    </svg>
  )
}

const TIP_MARGIN = 8
const TIP_GAP = 6

function VerificationAttemptBody({
  verification,
}: {
  verification: ImageVerificationSnapshot
}) {
  if (verification.status === 'error') {
    return (
      <section className="verify-mark__tip-section">
        <h4 className="verify-mark__tip-label">What happened</h4>
        <p className="verify-mark__tip-reason">
          {verification.error || 'The checker did not finish.'}
        </p>
      </section>
    )
  }

  const percent = verificationPercentLabel(verification)
  const outcome = verificationOutcomeLine(verification)
  const reason = verification.reasoning?.trim() || ''
  const axes = verificationAxisLines(verification)
  const mismatches = verificationMismatchLines(verification)

  return (
    <>
      {percent || outcome || axes.length > 0 ? (
        <section className="verify-mark__tip-section">
          <h4 className="verify-mark__tip-label">Match</h4>
          {percent ? <p className="verify-mark__tip-score">{percent}</p> : null}
          {outcome ? <p className="verify-mark__tip-outcome">{outcome}</p> : null}
          {axes.length > 0 ? (
            <p className="verify-mark__tip-outcome">{axes.join(' · ')}</p>
          ) : null}
        </section>
      ) : null}
      {reason ? (
        <section className="verify-mark__tip-section">
          <h4 className="verify-mark__tip-label">Reasoning</h4>
          <p className="verify-mark__tip-reason">{reason}</p>
        </section>
      ) : null}
      {mismatches.length > 0 ? (
        <section className="verify-mark__tip-section">
          <h4 className="verify-mark__tip-label">Issues found</h4>
          <ul className="verify-mark__tip-mismatches">
            {mismatches.map((line, index) => (
              <li key={index}>{line}</li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  )
}

function VerificationTipCard({ verification }: { verification: ImageVerification }) {
  const previous = verification.previous ?? null
  return (
    <>
      <header className="verify-mark__tip-head">
        <p className="verify-mark__tip-title">{verificationCardTitle(verification)}</p>
        <p className="verify-mark__tip-lede">
          Product look vs source photos, and on-image claims vs catalog. Quality is
          advisory.
        </p>
      </header>
      <VerificationAttemptBody verification={verification} />
      {previous ? (
        <section className="verify-mark__tip-prev">
          <h3 className="verify-mark__tip-prev-title">Earlier attempt</h3>
          <VerificationAttemptBody verification={previous} />
        </section>
      ) : null}
    </>
  )
}

function VerificationTip({
  anchor,
  children,
}: {
  anchor: HTMLElement
  children: ReactNode
}) {
  const tipRef = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)

  const place = useCallback(() => {
    const tip = tipRef.current
    if (!tip) return
    const mark = anchor.getBoundingClientRect()
    const box = tip.getBoundingClientRect()
    const maxLeft = window.innerWidth - box.width - TIP_MARGIN
    const left = Math.min(
      Math.max(mark.right - box.width, TIP_MARGIN),
      Math.max(maxLeft, TIP_MARGIN),
    )
    const above = mark.top - box.height - TIP_GAP
    const top = above >= TIP_MARGIN ? above : mark.bottom + TIP_GAP
    setPos({ top, left })
  }, [anchor])

  useLayoutEffect(() => {
    place()
    window.addEventListener('scroll', place, true)
    window.addEventListener('resize', place)
    return () => {
      window.removeEventListener('scroll', place, true)
      window.removeEventListener('resize', place)
    }
  }, [place])

  return createPortal(
    <div
      ref={tipRef}
      className="verify-mark__tip"
      role="tooltip"
      style={{
        position: 'fixed',
        top: pos?.top ?? 0,
        left: pos?.left ?? 0,
        visibility: pos ? 'visible' : 'hidden',
        zIndex: 120,
      }}
    >
      {children}
    </div>,
    document.body,
  )
}

export function VerificationMark({ verification }: { verification: ImageVerification }) {
  const anchorRef = useRef<HTMLSpanElement>(null)
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)

  if (verification.status === 'skipped') return null

  const passed =
    verification.status === 'ok' && !isVerificationBelowThreshold(verification)
  const tone = passed ? 'pass' : verification.status === 'error' ? 'error' : 'fail'
  const label = passed ? 'Verified' : verification.status === 'error' ? 'Unavailable' : 'Needs review'

  return (
    <span
      ref={anchorRef}
      className={`verify-mark verify-mark--${tone}`}
      aria-hidden="true"
      onMouseEnter={() => {
        setAnchor(anchorRef.current)
        setOpen(true)
      }}
      onMouseLeave={() => {
        setOpen(false)
        setAnchor(null)
      }}
      onClick={(event) => {
        event.preventDefault()
        event.stopPropagation()
      }}
    >
      {passed ? <PassCircleIcon /> : verification.status === 'error' ? <WarnCircleIcon /> : <FailCircleIcon />}
      <span className="verify-mark__label">{label}</span>
      {open && anchor ? (
        <VerificationTip anchor={anchor}>
          <VerificationTipCard verification={verification} />
        </VerificationTip>
      ) : null}
    </span>
  )
}
