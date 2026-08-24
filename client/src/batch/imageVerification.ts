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
  return mismatches.slice(0, 4).map((item) => {
    if (item.kind === 'invented') {
      return `Invented: “${item.observed ?? ''}”`
    }
    return `${item.source_field ?? 'Attribute'}: catalog ${item.catalog ?? '—'}, saw ${item.observed ?? '—'}`
  })
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
