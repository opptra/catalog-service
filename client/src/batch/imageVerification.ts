import type { ImageVerification, ImageVerificationSnapshot } from '../api/jobs'

export function isVerificationBelowThreshold(
  verification: ImageVerificationSnapshot | null | undefined,
): boolean {
  if (verification == null || verification.status !== 'ok') return false
  const confidence = verification.confidence
  const threshold = verification.threshold
  if (confidence == null || threshold == null) return false
  return confidence < threshold
}

export function verificationPercentLabel(
  verification: ImageVerificationSnapshot,
): string | null {
  return typeof verification.confidence === 'number'
    ? `${Math.round(verification.confidence)}%`
    : null
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
  if (axes == null) return []
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

export function verificationCardTitle(
  verification: ImageVerificationSnapshot,
): string {
  if (verification.status === 'error') return 'Verification unavailable'
  if (isVerificationBelowThreshold(verification)) return 'Needs review'
  if (verification.status === 'ok') return 'Verified with AI'
  return 'Image check'
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
  const title = verificationCardTitle(verification)
  const percent = verificationPercentLabel(verification)
  const previousPercent = verification.previous
    ? verificationPercentLabel(verification.previous)
    : null
  const previousBit = previousPercent ? ` Earlier attempt ${previousPercent}.` : ''
  if (percent) return ` ${title}, ${percent} match.${previousBit}`
  return ` ${title}.${previousBit}`
}
