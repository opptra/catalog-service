import magickWasmUrl from '@imagemagick/magick-wasm/magick.wasm?url'
import {
  ColorProfile,
  ColorSpace,
  ColorTransformMode,
  ImageMagick,
  MagickFormat,
  RenderingIntent,
  initializeImageMagick,
} from '@imagemagick/magick-wasm'
import { isTiff } from './ensureSrgbImage'
import { SRGB_ICC } from './srgbIcc'

let magickReady: Promise<void> | null = null

async function ensureMagick(): Promise<void> {
  if (magickReady === null) {
    magickReady = initializeImageMagick(new URL(magickWasmUrl, import.meta.url))
  }
  await magickReady
}

function jpegBlob(bytes: Uint8Array): Blob {
  const copy = bytes.slice()
  const buffer = copy.buffer
  if (!(buffer instanceof ArrayBuffer)) {
    throw new Error('JPEG convert produced an unexpected buffer')
  }
  return new Blob([buffer], { type: 'image/jpeg' })
}

/** Convert a CMYK JPEG or any TIFF to an sRGB JPEG using the file ICC when present. */
export async function convertToSrgbJpeg(bytes: Uint8Array): Promise<Blob> {
  await ensureMagick()
  const sourceIsTiff = isTiff(bytes)

  return ImageMagick.read(bytes, (image) => {
    const source = image.getColorProfile()
    if (image.colorSpace === ColorSpace.CMYK) {
      if (source !== null) {
        image.renderingIntent = RenderingIntent.Relative
        image.setArtifact('black-point-compensation', true)
        const ok = image.transformColorSpace(
          source,
          new ColorProfile(SRGB_ICC.slice()),
          ColorTransformMode.HighRes,
        )
        if (!ok) {
          throw new Error('Could not convert print image to sRGB')
        }
      } else if (!sourceIsTiff) {
        return jpegBlob(bytes)
      } else {
        image.colorSpace = ColorSpace.sRGB
      }
    } else if (sourceIsTiff && source !== null) {
      image.renderingIntent = RenderingIntent.Relative
      image.setArtifact('black-point-compensation', true)
      image.transformColorSpace(
        source,
        new ColorProfile(SRGB_ICC.slice()),
        ColorTransformMode.HighRes,
      )
    }

    image.quality = 95
    return image.write(MagickFormat.Jpeg, (data) => jpegBlob(data))
  })
}
