import type { ImageVerification, ImageVerificationSnapshot } from '../api/jobs'

export function verificationShipScore(
  verification: ImageVerificationSnapshot,
): number | null {
  const axes = verification.axes
  if (axes != null) {
    const identity = axes.identity
    const claims = axes.claims
    if (typeof identity === 'number' && typeof claims === 'number') {
      return Math.min(identity, claims)
    }
    if (typeof claims === 'number') {
      return claims
    }
  }
  return typeof verification.confidence === 'number' ? verification.confidence : null
}

export function isVerificationBelowThreshold(
  verification: ImageVerificationSnapshot | null | undefined,
): boolean {
  if (verification == null || verification.status !== 'ok') return false
  const score = verificationShipScore(verification)
  const threshold = verification.threshold
  if (score == null || threshold == null) return false
  return score < threshold
}

export function isTextVerification(
  verification: ImageVerificationSnapshot,
): boolean {
  const axes = verification.axes
  return axes != null && axes.identity == null && typeof axes.claims === 'number'
}

export function verificationStatusLabel(
  verification: ImageVerificationSnapshot,
): string {
  if (verification.status === 'error') {
    return isTextVerification(verification) ? 'Claims check unavailable' : 'Unavailable'
  }
  const passed =
    verification.status === 'ok' && !isVerificationBelowThreshold(verification)
  if (isTextVerification(verification)) {
    return passed ? 'Claims verified' : 'Claims need review'
  }
  return passed ? 'Verified' : 'Needs review'
}

export function verificationBadgeLabel(
  verification: ImageVerificationSnapshot,
): string | null {
  if (verification.status === 'skipped') return null
  const status = verificationStatusLabel(verification)
  const percent = verificationPercentLabel(verification)
  if (percent) return `${status} · ${percent}`
  return status
}

export function verificationBracketLabel(
  verification: ImageVerificationSnapshot,
): string | null {
  const badge = verificationBadgeLabel(verification)
  if (badge == null) return null
  return `[${badge}]`
}

export function verificationPercentLabel(
  verification: ImageVerificationSnapshot,
): string | null {
  const score = verificationShipScore(verification)
  return score == null ? null : `${Math.round(score)}%`
}

export function verificationMismatchLines(
  verification: ImageVerificationSnapshot,
): string[] {
  const mismatches = verification.mismatches ?? []
  return mismatches.slice(0, 6).map((item) => {
    if (item.kind === 'invented') {
      return `Invented: “${item.observed ?? ''}”`
    }
    if (item.kind === 'quality') {
      return `Quality: ${item.observed ?? '—'}`
    }
    if (item.kind === 'identity') {
      if (item.source_field && item.catalog) {
        return `Look: catalog ${item.source_field} ${item.catalog}, saw ${item.observed ?? '—'}`
      }
      return `Look: ${item.observed ?? '—'}`
    }
    return `${item.source_field ?? 'Attribute'}: catalog ${item.catalog ?? '—'}, saw ${item.observed ?? '—'}`
  })
}

export function verificationAxisLines(
  verification: ImageVerificationSnapshot,
): string[] {
  const axes = verification.axes
  if (axes == null || isTextVerification(verification)) return []
  const lines: string[] = []
  if (typeof axes.identity === 'number') {
    lines.push(`Identity ${Math.round(axes.identity)}%`)
  }
  if (typeof axes.claims === 'number') {
    lines.push(`Claims ${Math.round(axes.claims)}%`)
  }
  if (typeof axes.quality === 'number') {
    lines.push(`Quality ${Math.round(axes.quality)}%`)
  }
  return lines
}

export function verificationTooltipLede(
  verification: ImageVerificationSnapshot,
): string {
  if (isTextVerification(verification)) {
    return 'Checks stated claims against the fact sheet. Omitted catalog terms are fine.'
  }
  return 'Product look vs source photos, and on-image claims vs catalog. Quality is advisory.'
}

export function verificationCardTitle(
  verification: ImageVerificationSnapshot,
): string {
  if (verification.status === 'error') {
    return isTextVerification(verification)
      ? 'Claims check unavailable'
      : 'Verification unavailable'
  }
  if (isVerificationBelowThreshold(verification)) {
    return isTextVerification(verification) ? 'Claims need review' : 'Needs review'
  }
  if (verification.status === 'ok') {
    return isTextVerification(verification) ? 'Claims verified' : 'Verified with AI'
  }
  return isTextVerification(verification) ? 'Claims check' : 'Image check'
}

export function verificationOutcomeLine(
  verification: ImageVerificationSnapshot,
): string | null {
  if (verification.status === 'error') return null
  if (verification.threshold == null) return null
  return `${verification.threshold}% required`
}

export function verificationAriaSuffix(
  verification: ImageVerification | null | undefined,
): string {
  if (verification == null || verification.status === 'skipped') return ''
  const bracket = verificationBracketLabel(verification)
  const previousPercent = verification.previous
    ? verificationPercentLabel(verification.previous)
    : null
  const previousBit = previousPercent ? ` Earlier attempt ${previousPercent}.` : ''
  if (bracket) return ` ${bracket}.${previousBit}`
  return ` ${verificationCardTitle(verification)}.${previousBit}`
}
