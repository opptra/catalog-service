import type { SkuProductImage } from '../api/jobs'

const INPUT_ZIP_ROOT = 'images'

function safeFilename(value: string): string {
  const trimmed = value.trim().replace(/[/\\?%*:|"<>]/g, '_')
  return trimmed || 'sku'
}

function zipEntryName(filename: string): string {
  const base = filename.replace(/\\/g, '/').split('/').filter(Boolean).at(-1)
  if (base == null || base === '.' || base === '..') return 'image'
  return base
}

/**
 * Fetch signed product-image URLs and assemble images/{SKU}/{filename}
 * — the same layout batch upload expects.
 */
export async function downloadInputImagesZip(
  skuId: string,
  images: SkuProductImage[],
): Promise<void> {
  if (images.length === 0) {
    throw new Error('No input images available to download.')
  }

  const JSZip = (await import('jszip')).default
  const zip = new JSZip()
  const skuFolder = zip.folder(INPUT_ZIP_ROOT)?.folder(skuId)
  if (!skuFolder) {
    throw new Error('Could not create zip archive.')
  }

  const results = await Promise.allSettled(
    images.map(async (image) => {
      const response = await fetch(image.url)
      if (!response.ok) {
        throw new Error(`Failed to fetch ${image.filename} (${response.status})`)
      }
      const data = await response.arrayBuffer()
      return { image, data }
    }),
  )

  const usedNames = new Set<string>()
  let wrote = 0
  for (const result of results) {
    if (result.status !== 'fulfilled') continue
    const { image, data } = result.value
    let name = zipEntryName(image.filename)
    if (usedNames.has(name)) {
      const dot = name.lastIndexOf('.')
      const stem = dot > 0 ? name.slice(0, dot) : name
      const ext = dot > 0 ? name.slice(dot) : ''
      let n = 2
      while (usedNames.has(`${stem}_${n}${ext}`)) n += 1
      name = `${stem}_${n}${ext}`
    }
    usedNames.add(name)
    skuFolder.file(name, data)
    wrote += 1
  }

  if (wrote === 0) {
    throw new Error('Could not download any images. Please try again.')
  }

  const blob = await zip.generateAsync({ type: 'blob' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${safeFilename(skuId)}_images.zip`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
