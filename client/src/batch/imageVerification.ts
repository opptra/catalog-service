import type { ImageVerification } from '../api/jobs'

export function isVerificationBelowThreshold(
  verification: ImageVerification | null | undefined,
): boolean {
  if (verification == null || verification.status !== 'ok') return false
  const confidence = verification.confidence
  const threshold = verification.threshold
  if (confidence == null || threshold == null) return false
  return confidence < threshold
}

export function verificationScoreLabel(
  verification: ImageVerification,
): string | null {
  if (verification.status === 'error') return 'n/a'
  if (verification.status === 'ok' && verification.confidence != null) {
    return `${verification.confidence}%`
  }
  return null
}
