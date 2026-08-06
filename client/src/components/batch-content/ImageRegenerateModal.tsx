interface ImageRegenerateModalProps {
  open: boolean
  headerLabel: string
  imageUrl: string | null
  imageAlt: string
  canPrev: boolean
  canNext: boolean
  prompt: string
  onPromptChange: (value: string) => void
  onClose: () => void
  onPrev: () => void
  onNext: () => void
  /** Stub — no API call in this phase. */
  onRegenerate: () => void
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

function RefreshIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M13.5 8A5.5 5.5 0 1 1 11.2 3.4M13.5 8V3.5H9"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function ImageRegenerateModal({
  open,
  headerLabel,
  imageUrl,
  imageAlt,
  canPrev,
  canNext,
  prompt,
  onPromptChange,
  onClose,
  onPrev,
  onNext,
  onRegenerate,
}: ImageRegenerateModalProps) {
  if (!open) return null

  return (
    <div className="img-modal" role="presentation">
      <button type="button" className="img-modal__backdrop" aria-label="Close" onClick={onClose} />
      <div
        className="img-modal__dialog"
        role="dialog"
        aria-modal="true"
        aria-label={headerLabel}
      >
        <div className="img-modal__header">
          <p className="img-modal__context">{headerLabel}</p>
          <button type="button" className="img-modal__close" onClick={onClose} aria-label="Close">
            <CloseIcon />
          </button>
        </div>

        <div className="img-modal__preview">
          {imageUrl ? (
            <img src={imageUrl} alt={imageAlt} />
          ) : (
            <div className="img-modal__placeholder">No image</div>
          )}
        </div>

        <div className="img-modal__prompt-row">
          <input
            type="text"
            className="img-modal__prompt"
            value={prompt}
            onChange={(event) => onPromptChange(event.target.value)}
            placeholder='regenerate this image: "brighter background, side angle"'
          />
          <button
            type="button"
            className="img-modal__regen"
            onClick={onRegenerate}
            aria-label="Regenerate image"
            title="Regenerate (coming soon)"
          >
            <RefreshIcon />
          </button>
        </div>

        <div className="img-modal__footer">
          <button type="button" className="img-modal__nav" onClick={onPrev} disabled={!canPrev}>
            ← prev image
          </button>
          <button type="button" className="img-modal__nav" onClick={onNext} disabled={!canNext}>
            next image →
          </button>
        </div>
      </div>
    </div>
  )
}

export default ImageRegenerateModal
