import {
  completeFlatfileJob,
  createFlatfileJob,
  deleteWithSignedUrl,
  guessImageContentType,
  guessTemplateContentType,
  putToSignedUrl,
  type FlatfileImageFile,
} from '../api/flatfileJobs'
import {
  collectZipTopLevels,
  IMAGE_EXT,
  isIgnoredZipName,
  resolveZipRootPrefix,
} from '../lib/batchZip'
import type { BatchValidationResult } from '../lib/validateBatchFiles'
import {
  INITIAL_UPLOAD_STEPS,
  type UploadStatusStep,
  type UploadStatusStepId,
} from './batchUploadStore'

function markStep(
  steps: UploadStatusStep[],
  id: UploadStatusStepId,
  status: UploadStatusStep['status'],
  detail?: string,
): UploadStatusStep[] {
  return steps.map((step) =>
    step.id === id ? { ...step, status, detail: detail ?? undefined } : step,
  )
}

async function readZipImageBlobs(
  imagesFile: File,
): Promise<Map<string, Map<string, Blob>>> {
  const JSZip = (await import('jszip')).default
  const zip = await JSZip.loadAsync(await imagesFile.arrayBuffer())

  const zipPaths = Object.entries(zip.files).map(([path, entry]) => ({
    path,
    dir: entry.dir,
  }))
  const topLevels = collectZipTopLevels(zipPaths)
  const rootPrefix = resolveZipRootPrefix(topLevels)

  const bySku = new Map<string, Map<string, Blob>>()

  for (const [path, entry] of Object.entries(zip.files)) {
    if (entry.dir) continue
    const parts = path.replace(/\\/g, '/').split('/').filter(Boolean)
    if (parts.length === 0 || isIgnoredZipName(parts[0])) continue
    if (rootPrefix && parts[0] !== rootPrefix) continue
    const relative = rootPrefix ? parts.slice(1) : parts
    if (relative.length < 2) continue
    const skuId = relative[0]
    const filename = relative[relative.length - 1]
    if (filename.startsWith('.') || isIgnoredZipName(skuId) || isIgnoredZipName(filename)) {
      continue
    }
    if (!IMAGE_EXT.test(filename)) continue

    let files = bySku.get(skuId)
    if (!files) {
      files = new Map()
      bySku.set(skuId, files)
    }
    files.set(filename, await entry.async('blob'))
  }

  return bySku
}

const IMAGE_UPLOAD_CONCURRENCY = 10

/** Run async work over ``items`` with at most ``concurrency`` in flight. */
async function mapPool<T>(
  items: readonly T[],
  concurrency: number,
  worker: (item: T) => Promise<void>,
): Promise<void> {
  if (items.length === 0) return
  const limit = Math.max(1, Math.min(concurrency, items.length))
  let nextIndex = 0

  async function runWorker(): Promise<void> {
    while (nextIndex < items.length) {
      const index = nextIndex
      nextIndex += 1
      await worker(items[index])
    }
  }

  await Promise.all(Array.from({ length: limit }, () => runWorker()))
}

export interface RunFlatfileUploadInput {
  brandExternalId: string
  categoryExternalId: string
  productFile: File
  imagesFile: File
  result: BatchValidationResult
  onSteps: (steps: UploadStatusStep[]) => void
}

/** Runs the flatfile upload pipeline once. Progress is reported via ``onSteps``. */
export async function runFlatfileUpload(input: RunFlatfileUploadInput): Promise<void> {
  const { brandExternalId, categoryExternalId, productFile, imagesFile, result, onSteps } =
    input

  let steps = INITIAL_UPLOAD_STEPS.map((step) => ({ ...step }))
  const report = (next: UploadStatusStep[]) => {
    steps = next
    onSteps(steps)
  }

  report(markStep(steps, 'prepare', 'running'))

  const images: FlatfileImageFile[] = []
  for (const entry of result.skuImages) {
    for (const filename of entry.filenames) {
      images.push({
        sku_id: entry.sku_id,
        filename,
        content_type: guessImageContentType(filename),
      })
    }
  }
  if (images.length === 0) {
    throw new Error('No validated images to upload.')
  }

  const created = await createFlatfileJob({
    brand_external_id: brandExternalId,
    category_external_id: categoryExternalId,
    template_filename: productFile.name,
    template_content_type: guessTemplateContentType(productFile.name),
    images,
  })
  report(markStep(steps, 'prepare', 'passed'))

  report(markStep(steps, 'product', 'running'))
  if (!created.template.upload_url || !created.template.content_type) {
    throw new Error('Missing template upload URL.')
  }
  await putToSignedUrl(
    created.template.upload_url,
    productFile,
    created.template.content_type,
  )
  report(markStep(steps, 'product', 'passed'))

  report(markStep(steps, 'images', 'running'))
  const zipBlobs = await readZipImageBlobs(imagesFile)

  const remainingBySku = new Map<string, number>()
  for (const item of created.images) {
    if (item.sku_id == null) {
      throw new Error('Incomplete image upload URL payload.')
    }
    remainingBySku.set(item.sku_id, (remainingBySku.get(item.sku_id) ?? 0) + 1)
  }

  const productTotal = remainingBySku.size
  let productsDone = 0
  report(markStep(steps, 'images', 'running', `0 of ${productTotal} products`))

  await mapPool(created.images, IMAGE_UPLOAD_CONCURRENCY, async (item) => {
    if (item.sku_id == null || !item.filename || !item.upload_url || !item.content_type) {
      throw new Error('Incomplete image upload URL payload.')
    }
    const skuFiles = zipBlobs.get(item.sku_id)
    const blob = skuFiles?.get(item.filename)
    if (!blob) {
      throw new Error(`Missing zip file for SKU ${item.sku_id}/${item.filename}`)
    }
    await putToSignedUrl(item.upload_url, blob, item.content_type)

    const left = (remainingBySku.get(item.sku_id) ?? 1) - 1
    remainingBySku.set(item.sku_id, left)
    if (left === 0) {
      productsDone += 1
      report(
        markStep(
          steps,
          'images',
          'running',
          `${productsDone} of ${productTotal} products`,
        ),
      )
    }
  })

  const deletes = created.deletes.filter((item) => item.delete_url)
  await mapPool(deletes, IMAGE_UPLOAD_CONCURRENCY, async (item) => {
    if (!item.delete_url) return
    await deleteWithSignedUrl(item.delete_url)
  })

  report(
    markStep(steps, 'images', 'passed', `${productTotal} of ${productTotal} products`),
  )

  report(markStep(steps, 'finalize', 'running'))
  await completeFlatfileJob(created.external_id)
  report(markStep(steps, 'finalize', 'passed'))
}
