export const BATCH_STEPS = ['subcategory', 'upload', 'marketplace', 'generate'] as const

const SUBCATEGORY_KEY = 'listingStudio.batchSubcategory'
const FILES_KEY = 'listingStudio.batchFilesUploaded'

export interface BatchSubcategory {
  external_id: string
  name: string
}

function parseSubcategory(raw: string): BatchSubcategory | null {
  try {
    const parsed = JSON.parse(raw) as unknown
    if (
      typeof parsed === 'object' &&
      parsed !== null &&
      'external_id' in parsed &&
      'name' in parsed &&
      typeof (parsed as BatchSubcategory).external_id === 'string' &&
      typeof (parsed as BatchSubcategory).name === 'string'
    ) {
      return {
        external_id: (parsed as BatchSubcategory).external_id,
        name: (parsed as BatchSubcategory).name,
      }
    }
  } catch {
    // Legacy plain-string values from earlier drafts.
    if (raw.trim().length > 0) {
      return { external_id: '', name: raw }
    }
  }
  return null
}

export function getBatchSubcategory(): string | null {
  const raw = sessionStorage.getItem(SUBCATEGORY_KEY)
  if (!raw) return null
  return parseSubcategory(raw)?.name ?? null
}

export function getBatchSubcategorySelection(): BatchSubcategory | null {
  const raw = sessionStorage.getItem(SUBCATEGORY_KEY)
  if (!raw) return null
  return parseSubcategory(raw)
}

export function setBatchSubcategory(subcategory: BatchSubcategory): void {
  sessionStorage.setItem(SUBCATEGORY_KEY, JSON.stringify(subcategory))
}

export function clearBatchDraft(): void {
  sessionStorage.removeItem(SUBCATEGORY_KEY)
  sessionStorage.removeItem(FILES_KEY)
}

export function getBatchFilesUploaded(): boolean {
  return sessionStorage.getItem(FILES_KEY) === '1'
}

export function setBatchFilesUploaded(uploaded: boolean): void {
  if (uploaded) sessionStorage.setItem(FILES_KEY, '1')
  else sessionStorage.removeItem(FILES_KEY)
}
