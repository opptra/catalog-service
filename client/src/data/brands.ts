export interface Brand {
  id: string
  name: string
}

/** Placeholder until batch history is wired to the API. */
export const STATIC_LAST_BATCH_LABEL = 'last batch · 2h ago'

const SELECTED_BRAND_KEY = 'listingStudio.selectedBrand'

export function getSelectedBrand(): Brand | null {
  const raw = sessionStorage.getItem(SELECTED_BRAND_KEY)
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
    // Ignore corrupt session values.
  }
  return null
}

export function getSelectedBrandId(): string | null {
  return getSelectedBrand()?.id ?? null
}

export function setSelectedBrand(brand: Brand): void {
  sessionStorage.setItem(SELECTED_BRAND_KEY, JSON.stringify(brand))
}

export function clearSelectedBrand(): void {
  sessionStorage.removeItem(SELECTED_BRAND_KEY)
}
