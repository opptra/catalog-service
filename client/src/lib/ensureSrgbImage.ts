/** Detect print JPEGs and TIFFs. Conversion to sRGB JPEG runs in the browser with ImageMagick. */

const JPEG_NAME = /\.jpe?g$/i
const TIFF_NAME = /\.tiff?$/i

export const JPEG_CONTENT_TYPE = 'image/jpeg'
export const PNG_CONTENT_TYPE = 'image/png'
export const WEBP_CONTENT_TYPE = 'image/webp'

export function isJpegFilename(filename: string): boolean {
  return JPEG_NAME.test(filename)
}

export function isTiffFilename(filename: string): boolean {
  return TIFF_NAME.test(filename)
}

/** JPEG SOI, regardless of filename. */
export function isJpegBytes(bytes: Uint8Array): boolean {
  return bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff
}

export function isPngBytes(bytes: Uint8Array): boolean {
  return (
    bytes.length >= 8 &&
    bytes[0] === 0x89 &&
    bytes[1] === 0x50 &&
    bytes[2] === 0x4e &&
    bytes[3] === 0x47 &&
    bytes[4] === 0x0d &&
    bytes[5] === 0x0a &&
    bytes[6] === 0x1a &&
    bytes[7] === 0x0a
  )
}

export function isWebpBytes(bytes: Uint8Array): boolean {
  return (
    bytes.length >= 12 &&
    bytes[0] === 0x52 &&
    bytes[1] === 0x49 &&
    bytes[2] === 0x46 &&
    bytes[3] === 0x46 &&
    bytes[8] === 0x57 &&
    bytes[9] === 0x45 &&
    bytes[10] === 0x42 &&
    bytes[11] === 0x50
  )
}

export function replaceImageExtension(filename: string, extension: string): string {
  const lastDot = filename.lastIndexOf('.')
  if (lastDot <= 0) return `${filename}${extension}`
  return `${filename.slice(0, lastDot)}${extension}`
}

export interface StoredImageTarget {
  sourceFilename: string
  storedFilename: string
  contentType: string
  convert: boolean
}

function jpegStoredName(filename: string): string {
  return isJpegFilename(filename) ? filename : replaceImageExtension(filename, '.jpg')
}

/**
 * GCS object name + content type for one zip image.
 * TIFF / CMYK JPEG → sRGB JPEG stored as .jpg.
 * JPEG/PNG/WebP bytes behind a .tif name → matching extension (no Magick for already-JPEG).
 */
export function storedImageTarget(filename: string, bytes: Uint8Array): StoredImageTarget {
  const convert = needsSrgbJpegConvert(bytes)
  if (convert) {
    return {
      sourceFilename: filename,
      storedFilename: jpegStoredName(filename),
      contentType: JPEG_CONTENT_TYPE,
      convert: true,
    }
  }
  if (isTiffFilename(filename) && isJpegBytes(bytes)) {
    return {
      sourceFilename: filename,
      storedFilename: jpegStoredName(filename),
      contentType: JPEG_CONTENT_TYPE,
      convert: false,
    }
  }
  if (isTiffFilename(filename) && isPngBytes(bytes)) {
    return {
      sourceFilename: filename,
      storedFilename: replaceImageExtension(filename, '.png'),
      contentType: PNG_CONTENT_TYPE,
      convert: false,
    }
  }
  if (isTiffFilename(filename) && isWebpBytes(bytes)) {
    return {
      sourceFilename: filename,
      storedFilename: replaceImageExtension(filename, '.webp'),
      contentType: WEBP_CONTENT_TYPE,
      convert: false,
    }
  }
  return {
    sourceFilename: filename,
    storedFilename: filename,
    contentType: imageContentTypeFromFilename(filename),
    convert: false,
  }
}

export function imageContentTypeFromFilename(filename: string): string {
  const lower = filename.toLowerCase()
  if (lower.endsWith('.png')) return PNG_CONTENT_TYPE
  if (lower.endsWith('.gif')) return 'image/gif'
  if (lower.endsWith('.webp')) return WEBP_CONTENT_TYPE
  if (lower.endsWith('.bmp')) return 'image/bmp'
  if (lower.endsWith('.tif') || lower.endsWith('.tiff')) return 'image/tiff'
  return JPEG_CONTENT_TYPE
}

/** TIFF / BigTIFF little-endian (`II`) or big-endian (`MM`), regardless of filename. */
export function isTiff(bytes: Uint8Array): boolean {
  if (bytes.length < 4) return false
  const little = bytes[0] === 0x49 && bytes[1] === 0x49
  const big = bytes[0] === 0x4d && bytes[1] === 0x4d
  if (little && bytes[3] === 0x00 && (bytes[2] === 0x2a || bytes[2] === 0x2b)) return true
  if (big && bytes[2] === 0x00 && (bytes[3] === 0x2a || bytes[3] === 0x2b)) return true
  return false
}

export function isCmykJpeg(bytes: Uint8Array): boolean {
  return jpegComponentCount(bytes) === 4
}

/** Files Magick must turn into sRGB JPEG before the single GCS PUT. */
export function needsSrgbJpegConvert(bytes: Uint8Array): boolean {
  return isTiff(bytes) || isCmykJpeg(bytes)
}

/** SOF `Nf` — 3 is YCbCr/RGB, 4 is CMYK or YCCK. */
export function jpegComponentCount(bytes: Uint8Array): number | null {
  if (bytes.length < 4 || bytes[0] !== 0xff || bytes[1] !== 0xd8) return null

  let offset = 2
  while (offset < bytes.length) {
    if (bytes[offset] !== 0xff) {
      offset += 1
      continue
    }
    while (offset < bytes.length && bytes[offset] === 0xff) {
      offset += 1
    }
    if (offset >= bytes.length) return null

    const marker = bytes[offset]
    offset += 1
    if (marker === 0xd8 || marker === 0xd9 || marker === 0x01) continue
    if (marker >= 0xd0 && marker <= 0xd7) continue
    if (marker === 0xda) return null
    if (offset + 1 >= bytes.length) return null

    const length = (bytes[offset] << 8) | bytes[offset + 1]
    if (length < 2 || offset + length > bytes.length) return null

    const isSof =
      (marker >= 0xc0 && marker <= 0xc3) ||
      (marker >= 0xc5 && marker <= 0xc7) ||
      (marker >= 0xc9 && marker <= 0xcb) ||
      (marker >= 0xcd && marker <= 0xcf)
    if (isSof && length >= 8) {
      return bytes[offset + 7]
    }
    offset += length
  }
  return null
}
