export interface Brand {
  id: string
  name: string
}

/** Placeholder until batch history is wired to the API. */
export const STATIC_LAST_BATCH_LABEL = 'last batch · 2h ago'

const SELECTED_BRAND_KEY = 'listingStudio.selectedBrand'

function readRawSelectedBrand(): string | null {
  const fromLocal = localStorage.getItem(SELECTED_BRAND_KEY)
  if (fromLocal) return fromLocal

  // Migrate older session-scoped selection so new tabs keep the same brand.
  const fromSession = sessionStorage.getItem(SELECTED_BRAND_KEY)
  if (fromSession) {
    localStorage.setItem(SELECTED_BRAND_KEY, fromSession)
    sessionStorage.removeItem(SELECTED_BRAND_KEY)
    return fromSession
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
  localStorage.setItem(SELECTED_BRAND_KEY, JSON.stringify(brand))
  sessionStorage.removeItem(SELECTED_BRAND_KEY)
}

export function clearSelectedBrand(): void {
  localStorage.removeItem(SELECTED_BRAND_KEY)
  sessionStorage.removeItem(SELECTED_BRAND_KEY)
}
