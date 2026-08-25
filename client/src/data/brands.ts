export interface Brand {
  id: string
  name: string
}

const SELECTED_BRAND_KEY = 'listingStudio.selectedBrand'

function readRawSelectedBrand(): string | null {
  const fromSession = sessionStorage.getItem(SELECTED_BRAND_KEY)
  if (fromSession) return fromSession

  const fromLocal = localStorage.getItem(SELECTED_BRAND_KEY)
  if (fromLocal) {
    sessionStorage.setItem(SELECTED_BRAND_KEY, fromLocal)
    localStorage.removeItem(SELECTED_BRAND_KEY)
    return fromLocal
  }

  return null
}

export function getSelectedBrand(): Brand | null {
  const raw = readRawSelectedBrand()
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as unknown
    if (
      typeof parsed === 'object' &&
      parsed !== null &&
      'id' in parsed &&
      'name' in parsed &&
      typeof (parsed as Brand).id === 'string' &&
      typeof (parsed as Brand).name === 'string'
    ) {
      return { id: (parsed as Brand).id, name: (parsed as Brand).name }
    }
  } catch {
    // Ignore corrupt stored values.
  }
  return null
}

export function getSelectedBrandId(): string | null {
  return getSelectedBrand()?.id ?? null
}

export function setSelectedBrand(brand: Brand): void {
  sessionStorage.setItem(SELECTED_BRAND_KEY, JSON.stringify(brand))
  localStorage.removeItem(SELECTED_BRAND_KEY)
}

export function clearSelectedBrand(): void {
  sessionStorage.removeItem(SELECTED_BRAND_KEY)
  localStorage.removeItem(SELECTED_BRAND_KEY)
}

export function formatLastBatchLabel(lastBatchAt: string | null | undefined): string {
  if (!lastBatchAt) return 'No batches yet'
  const then = new Date(lastBatchAt).getTime()
  const now = Date.now()
  const diffMs = Math.max(0, now - then)
  const minutes = Math.floor(diffMs / 60_000)
  if (minutes < 1) return 'last batch · just now'
  if (minutes < 60) return `last batch · ${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `last batch · ${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `last batch · ${days}d ago`
  return `last batch · ${new Date(lastBatchAt).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
  })}`
}
