import type { SkuImageDownloadResponse } from '../api/jobs'

/** Fetch each signed image URL, assemble images/{folder}/{filename}, trigger zip download. */
export async function downloadSkuImagesZip(payload: SkuImageDownloadResponse): Promise<void> {
  if (payload.images.length === 0) {
    throw new Error('No images available to download.')
  }

  const JSZip = (await import('jszip')).default
  const zip = new JSZip()
  const imagesRoot = zip.folder('images')
  if (!imagesRoot) {
    throw new Error('Could not create zip archive.')
  }

  const results = await Promise.allSettled(
    payload.images.map(async (image) => {
      const response = await fetch(image.url)
      if (!response.ok) {
        throw new Error(`Failed to fetch ${image.filename} (${response.status})`)
      }
      const data = await response.arrayBuffer()
      return { image, data }
    }),
  )

  let wrote = 0
  for (const result of results) {
    if (result.status !== 'fulfilled') continue
    const { image, data } = result.value
    const folder = imagesRoot.folder(image.folder)
    if (!folder) continue
    folder.file(image.filename, data)
    wrote += 1
  }

  if (wrote === 0) {
    throw new Error('Could not download any images. Please try again.')
  }

  const blob = await zip.generateAsync({ type: 'blob' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = payload.filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
