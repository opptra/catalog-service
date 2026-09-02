import { useEffect, useState } from 'react'
import axios from 'axios'
import { getSkuProductImages, type SkuProductImage } from '../../api/jobs'

interface ProductImagesCarouselProps {
  open: boolean
  skuGenerationJobExternalId: string | null
  skuLabel: string
  onClose: () => void
}

function CloseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M4 4L12 12M12 4L4 12"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  )
}

function ChevronLeftIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M10 3.5L5.5 8L10 12.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function ChevronRightIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M6 3.5L10.5 8L6 12.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function DownloadIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M8 2.5V10.5M8 10.5L5 7.5M8 10.5L11 7.5M3 13.5H13"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function formatLoadError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (error.message) return error.message
  }
  if (error instanceof Error && error.message) return error.message
  return 'Could not load input images.'
}

function ProductImagesCarousel({
  open,
  skuGenerationJobExternalId,
  skuLabel,
  onClose,
}: ProductImagesCarouselProps) {
  const [skuId, setSkuId] = useState('')
  const [images, setImages] = useState<SkuProductImage[]>([])
  const [index, setIndex] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [zipping, setZipping] = useState(false)
  const [zipError, setZipError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || skuGenerationJobExternalId == null) return

    let cancelled = false
    setSkuId('')
    setImages([])
    setIndex(0)
    setError(null)
    setZipError(null)
    setLoading(true)

    void getSkuProductImages(skuGenerationJobExternalId)
      .then((data) => {
        if (cancelled) return
        setSkuId(data.sku_id)
        setImages(data.images)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(formatLoadError(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [open, skuGenerationJobExternalId])

  useEffect(() => {
    if (!open) return

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose()
        return
      }
      if (event.key === 'ArrowLeft') {
        event.preventDefault()
        setIndex((current) => Math.max(0, current - 1))
      }
      if (event.key === 'ArrowRight') {
        event.preventDefault()
        setIndex((current) => {
          if (images.length === 0) return 0
          return Math.min(images.length - 1, current + 1)
        })
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, onClose, images.length])

  const lastIndex = Math.max(images.length - 1, 0)
  const safeIndex = Math.min(index, lastIndex)
  const current = images[safeIndex]
  const canPrev = safeIndex > 0
  const canNext = safeIndex < lastIndex
  const canZip = !loading && error == null && images.length > 0 && skuId.length > 0 && !zipping

  async function handleDownloadZip() {
    if (!canZip) return
    setZipError(null)
    setZipping(true)
    try {
      const { downloadInputImagesZip } = await import('../../lib/downloadInputImagesZip')
      await downloadInputImagesZip(skuId, images)
    } catch (err: unknown) {
      setZipError(
        err instanceof Error && err.message ? err.message : 'Could not download ZIP.',
      )
    } finally {
      setZipping(false)
    }
  }

  if (!open) return null

  return (
    <div className="img-modal" role="presentation">
      <button
        type="button"
        className="img-modal__backdrop"
        aria-label="Close"
        onClick={onClose}
      />
      <div
        className="img-modal__dialog img-modal__dialog--wide"
        role="dialog"
        aria-modal="true"
        aria-label={`Input images · ${skuLabel}`}
      >
        <div className="img-modal__header">
          <p className="img-modal__context">
            Input images · {skuLabel}
            {images.length > 0 ? ` · ${safeIndex + 1} of ${images.length}` : ''}
          </p>
          <div className="img-modal__header-actions">
            <button
              type="button"
              className="img-modal__export"
              onClick={() => void handleDownloadZip()}
              disabled={!canZip}
            >
              <DownloadIcon />
              {zipping ? 'Preparing…' : 'Download as ZIP'}
            </button>
            <button type="button" className="img-modal__close" onClick={onClose} aria-label="Close">
              <CloseIcon />
            </button>
          </div>
        </div>

        {zipError != null ? (
          <p className="product-images-carousel__error product-images-carousel__zip-error">
            {zipError}
          </p>
        ) : null}

        <div className="img-modal__preview product-images-carousel__preview">
          {loading ? (
            <span
              className="img-modal__placeholder content-shimmer"
              aria-busy="true"
              aria-label="Loading images"
            />
          ) : error != null ? (
            <p className="img-modal__placeholder product-images-carousel__error">{error}</p>
          ) : current == null ? (
            <p className="img-modal__placeholder">No input images found for this SKU.</p>
          ) : (
            <img
              src={current.url}
              alt={current.filename}
              decoding="async"
            />
          )}
        </div>

        {current != null ? (
          <p className="product-images-carousel__filename">{current.filename}</p>
        ) : null}

        {images.length > 1 ? (
          <div className="product-images-carousel__thumbs" aria-label="Product photos">
            {images.map((image, imageIndex) => {
              const selected = imageIndex === safeIndex
              return (
                <button
                  key={image.filename}
                  type="button"
                  className={`product-images-carousel__thumb${
                    selected ? ' product-images-carousel__thumb--active' : ''
                  }`}
                  onClick={() => setIndex(imageIndex)}
                  aria-label={`Show image ${imageIndex + 1}, ${image.filename}`}
                  aria-current={selected ? 'true' : undefined}
                >
                  <img src={image.url} alt="" loading="lazy" decoding="async" />
                </button>
              )
            })}
          </div>
        ) : null}

        {images.length > 1 ? (
          <div className="img-modal__footer">
            <button
              type="button"
              className="img-modal__nav"
              onClick={() => setIndex((currentIndex) => Math.max(0, currentIndex - 1))}
              disabled={!canPrev}
            >
              <ChevronLeftIcon />
              Previous
            </button>
            <button
              type="button"
              className="img-modal__nav"
              onClick={() => setIndex((currentIndex) => Math.min(lastIndex, currentIndex + 1))}
              disabled={!canNext}
            >
              Next
              <ChevronRightIcon />
            </button>
          </div>
        ) : null}
      </div>
    </div>
  )
}

export default ProductImagesCarousel
