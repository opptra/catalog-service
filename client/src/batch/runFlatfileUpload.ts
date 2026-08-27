import {
  completeFlatfileJob,
  createFlatfileJob,
  deleteWithSignedUrl,
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
import { storedImageTarget } from '../lib/ensureSrgbImage'
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
/** Magick is CPU-heavy. One at a time keeps older Windows laptops from locking up. */
const PRINT_CONVERT_CONCURRENCY = 1

function yieldToUi(): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, 0)
  })
}

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
  const { categoryExternalId, productFile, imagesFile, result, onSteps } = input

  let steps = INITIAL_UPLOAD_STEPS.map((step) => ({ ...step }))
  const report = (next: UploadStatusStep[]) => {
    steps = next
    onSteps(steps)
  }

  report(markStep(steps, 'prepare', 'running'))

  const zipBlobs = await readZipImageBlobs(imagesFile)
  const convertJobs: Array<{
    skuId: string
    sourceFilename: string
    storedFilename: string
    bytes: Uint8Array
  }> = []
  const images: FlatfileImageFile[] = []
  const claimedStored = new Map<string, string>()
  for (const entry of result.skuImages) {
    const skuFiles = zipBlobs.get(entry.sku_id)
    for (const filename of entry.filenames) {
      const blob = skuFiles?.get(filename)
      if (!skuFiles || !blob) {
        throw new Error(`Missing zip file for SKU ${entry.sku_id}/${filename}`)
      }
      const bytes = new Uint8Array(await blob.arrayBuffer())
      const target = storedImageTarget(filename, bytes)
      const claimKey = `${entry.sku_id}/${target.storedFilename}`
      const prior = claimedStored.get(claimKey)
      if (prior !== undefined) {
        throw new Error(
          `SKU ${entry.sku_id}: “${prior}” and “${filename}” would both upload as ${target.storedFilename}`,
        )
      }
      claimedStored.set(claimKey, filename)
      if (target.convert) {
        convertJobs.push({
          skuId: entry.sku_id,
          sourceFilename: filename,
          storedFilename: target.storedFilename,
          bytes,
        })
      } else if (target.storedFilename !== filename) {
        skuFiles.set(target.storedFilename, blob)
      }
      images.push({
        sku_id: entry.sku_id,
        filename: target.storedFilename,
        content_type: target.contentType,
      })
    }
  }
  if (images.length === 0) {
    throw new Error('No validated images to upload.')
  }

  const created = await createFlatfileJob({
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

  const remainingBySku = new Map<string, number>()
  for (const item of created.images) {
    if (item.sku_id == null) {
      throw new Error('Incomplete image upload URL payload.')
    }
    remainingBySku.set(item.sku_id, (remainingBySku.get(item.sku_id) ?? 0) + 1)
  }

  const productTotal = remainingBySku.size
  if (convertJobs.length > 0) {
    const { convertToSrgbJpeg } = await import('../lib/convertCmykJpegToSrgb')
    let convertedDone = 0
    report(
      markStep(
        steps,
        'images',
        'running',
        `Converting print colors 0 of ${convertJobs.length}`,
      ),
    )
    await mapPool(convertJobs, PRINT_CONVERT_CONCURRENCY, async (job) => {
      const converted = await convertToSrgbJpeg(job.bytes)
      const skuFiles = zipBlobs.get(job.skuId)
      if (!skuFiles) {
        throw new Error(`Missing zip file for SKU ${job.skuId}/${job.sourceFilename}`)
      }
      skuFiles.set(job.storedFilename, converted)
      convertedDone += 1
      report(
        markStep(
          steps,
          'images',
          'running',
          `Converting print colors ${convertedDone} of ${convertJobs.length}`,
        ),
      )
      await yieldToUi()
    })
  }

  let productsDone = 0
  report(markStep(steps, 'images', 'running', `0 of ${productTotal} products`))

  await mapPool(created.images, IMAGE_UPLOAD_CONCURRENCY, async (item) => {
    const filename = item.filename
    if (item.sku_id == null || filename == null || filename === '' || !item.upload_url || !item.content_type) {
      throw new Error('Incomplete image upload URL payload.')
    }
    const skuFiles = zipBlobs.get(item.sku_id)
    const blob = skuFiles?.get(filename)
    if (!blob) {
      throw new Error(`Missing zip file for SKU ${item.sku_id}/${filename}`)
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
