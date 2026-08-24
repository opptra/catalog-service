import type { ContentImage } from './types'
import {
  isVerificationBelowThreshold,
  verificationScoreLabel,
} from '../../batch/imageVerification'

interface ContentImageGridProps {
  title: string
  hint: string
  images: ContentImage[]
  onSelect: (index: number) => void
}

function ContentImageGrid({ title, hint, images, onSelect }: ContentImageGridProps) {
  return (
    <section className="content-section content-section--images">
      <div className="content-section__head">
        <h3 className="content-section__label">{title}</h3>
        <p className="content-section__hint">{hint}</p>
      </div>
      <div className="pdp-grid">
        {images.map((image, index) => {
          const url = image.url
          const ready = typeof url === 'string' && url.trim() !== ''
          const verification = image.verification
          const score = verification ? verificationScoreLabel(verification) : null
          const low = isVerificationBelowThreshold(verification)
          const retried = (verification?.attempt ?? 1) > 1
          return (
            <button
              key={image.id}
              type="button"
              className={`pdp-tile${ready ? '' : ' pdp-tile--loading'}`}
              onClick={() => {
                if (ready) onSelect(index)
              }}
              disabled={!ready}
              aria-label={ready ? `Open ${image.label}` : `Generating ${image.label}`}
              aria-busy={!ready}
            >
              {ready ? (
                <img src={url} alt="" className="pdp-tile__img" />
              ) : (
                <span className="pdp-tile__empty content-shimmer" aria-hidden="true" />
              )}
              <span className="pdp-tile__badge">{index + 1}</span>
              {score != null ? (
                <span
                  className={`pdp-tile__verify${low ? ' pdp-tile__verify--low' : ''}${retried ? ' pdp-tile__verify--retried' : ''}`}
                >
                  {score}
                  {retried ? ' · retried' : ''}
                </span>
              ) : null}
            </button>
          )
        })}
      </div>
    </section>
  )
}

export default ContentImageGrid
