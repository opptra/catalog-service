import { create } from 'zustand'
import type { BatchValidationResult, ValidationStep } from '../lib/validateBatchFiles'
import { useMarketplaceSelectionStore } from './marketplaceSelectionStore'
import { runFlatfileUpload } from './runFlatfileUpload'

export type UploadPhase = 'idle' | 'uploading' | 'done' | 'error'

export type UploadStatusStepId =
  | 'prepare'
  | 'product'
  | 'images'
  | 'finalize'

export type UploadStatusStepState = 'pending' | 'running' | 'passed' | 'failed'

export interface UploadStatusStep {
  id: UploadStatusStepId
  label: string
  status: UploadStatusStepState
  detail?: string
}

interface BatchUploadState {
  productFile: File | null
  imagesFile: File | null
  validating: boolean
  steps: ValidationStep[]
  result: BatchValidationResult | null
  uploadPhase: UploadPhase
  uploadSteps: UploadStatusStep[]
  uploadError: string | null
  setFiles: (productFile: File, imagesFile: File) => void
  setValidating: (validating: boolean) => void
  setSteps: (steps: ValidationStep[]) => void
  setResult: (result: BatchValidationResult | null) => void
  clearValidation: () => void
  /** Start the flatfile upload if idle/error. Safe to call twice (Strict Mode). */
  startUpload: (categoryExternalId: string) => Promise<void>
  resetUpload: () => void
  clear: () => void
}

const INITIAL_UPLOAD_STEPS: UploadStatusStep[] = [
  { id: 'prepare', label: 'Preparing files', status: 'pending' },
  { id: 'product', label: 'Uploading product data', status: 'pending' },
  { id: 'images', label: 'Uploading images', status: 'pending' },
  { id: 'finalize', label: 'Finalizing batch upload', status: 'pending' },
]

export const useBatchUploadStore = create<BatchUploadState>((set, get) => ({
  productFile: null,
  imagesFile: null,
  validating: false,
  steps: [],
  result: null,
  uploadPhase: 'idle',
  uploadSteps: INITIAL_UPLOAD_STEPS,
  uploadError: null,

  setFiles: (productFile, imagesFile) =>
    set({
      productFile,
      imagesFile,
      result: null,
      steps: [],
      validating: false,
      uploadPhase: 'idle',
      uploadSteps: INITIAL_UPLOAD_STEPS,
      uploadError: null,
    }),

  setValidating: (validating) => set({ validating }),

  setSteps: (steps) => set({ steps }),

  setResult: (result) => set({ result, validating: false }),

  clearValidation: () =>
    set({
      result: null,
      steps: [],
      validating: false,
      uploadPhase: 'idle',
      uploadSteps: INITIAL_UPLOAD_STEPS,
      uploadError: null,
    }),

  startUpload: async (categoryExternalId) => {
    const { productFile, imagesFile, result, uploadPhase } = get()
    if (uploadPhase === 'uploading' || uploadPhase === 'done') return
    if (!productFile || !imagesFile || !result || result.skuImages.length <= 0) return
    if (!categoryExternalId) return

    set({
      uploadPhase: 'uploading',
      uploadError: null,
      uploadSteps: INITIAL_UPLOAD_STEPS.map((step) => ({ ...step })),
    })

    try {
      await runFlatfileUpload({
        categoryExternalId,
        productFile,
        imagesFile,
        result,
        onSteps: (uploadSteps) => set({ uploadSteps }),
      })
      set({ uploadPhase: 'done' })
    } catch (error) {
      set({
        uploadPhase: 'error',
        uploadError: error instanceof Error ? error.message : 'Upload failed.',
      })
    }
  },

  resetUpload: () =>
    set({
      uploadPhase: 'idle',
      uploadSteps: INITIAL_UPLOAD_STEPS,
      uploadError: null,
    }),

  clear: () => {
    useMarketplaceSelectionStore.getState().clear()
    set({
      productFile: null,
      imagesFile: null,
      validating: false,
      steps: [],
      result: null,
      uploadPhase: 'idle',
      uploadSteps: INITIAL_UPLOAD_STEPS,
      uploadError: null,
    })
  },
}))

export { INITIAL_UPLOAD_STEPS }
