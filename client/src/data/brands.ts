export interface Brand {
  id: string
  name: string
}

/** Placeholder until batch history is wired to the API. */
export const STATIC_LAST_BATCH_LABEL = 'last batch · 2h ago'

const SELECTED_BRAND_KEY = 'listingStudio.selectedBrand'

function readRawSelectedBrand(): string | null {
  const fromSession = sessionStorage.getItem(SELECTED_BRAND_KEY)
  if (fromSession) return fromSession

  // One-time migrate from the old shared localStorage key so this tab keeps
  // its previous selection, then clear localStorage so tabs stay isolated.
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
