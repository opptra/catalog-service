export const BATCH_STEPS = ['subcategory', 'upload', 'marketplace', 'generate'] as const

const SUBCATEGORY_KEY = 'listingStudio.batchSubcategory'
const FILES_KEY = 'listingStudio.batchFilesUploaded'

export function getBatchSubcategory(): string | null {
  return sessionStorage.getItem(SUBCATEGORY_KEY)
}

export function setBatchSubcategory(subcategory: string): void {
  sessionStorage.setItem(SUBCATEGORY_KEY, subcategory)
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
