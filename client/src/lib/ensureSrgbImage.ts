/** Detect print JPEGs and TIFFs. Conversion to sRGB JPEG runs in the browser with ImageMagick. */

const JPEG_NAME = /\.jpe?g$/i

export const JPEG_CONTENT_TYPE = 'image/jpeg'

export function isJpegFilename(filename: string): boolean {
  return JPEG_NAME.test(filename)
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
