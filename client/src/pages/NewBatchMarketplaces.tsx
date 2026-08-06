import { useEffect, useMemo, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import iconInfo from '../assets/icon-info.svg'
import iconLock from '../assets/icon-lock.svg'
import BatchShell from '../components/BatchShell'
import { getBatchSubcategory } from '../data/batchDraft'

interface MarketplaceOption {
  id: string
  label: string
  count?: number
}

interface Marketplace {
  id: string
  name: string
  options: MarketplaceOption[]
}

const MARKETPLACES: Marketplace[] = [
  {
    id: 'amazon',
    name: 'Amazon',
    options: [
      { id: 'title', label: 'Title' },
      { id: 'description', label: 'Description' },
      { id: 'highlights', label: 'Item highlights' },
      { id: 'aplus', label: 'A+ content' },
      { id: 'pdp', label: 'PDP images', count: 10 },
    ],
  },
  {
    id: 'flipkart',
    name: 'Flipkart',
    options: [
      { id: 'title', label: 'Title' },
      { id: 'description', label: 'Description' },
      { id: 'bullets', label: 'Bullet points' },
      { id: 'pdp', label: 'PDP images', count: 6 },
    ],
  },
  {
    id: 'myntra',
    name: 'Myntra',
    options: [
      { id: 'title', label: 'Title' },
      { id: 'description', label: 'Description' },
      { id: 'bullets', label: 'Bullets' },
      { id: 'pdp', label: 'PDP images', count: 5 },
    ],
  },
]

const SKU_COUNT = 12

function NewBatchMarketplaces() {
  const navigate = useNavigate()
  const subcategory = getBatchSubcategory()
  const [selected, setSelected] = useState<Record<string, Set<string>>>(() => ({
    amazon: new Set(
      MARKETPLACES.find((item) => item.id === 'amazon')?.options.map((option) => option.id) ?? [],
    ),
    flipkart: new Set(
      MARKETPLACES.find((item) => item.id === 'flipkart')?.options.map((option) => option.id) ?? [],
    ),
    myntra: new Set(),
  }))

  useEffect(() => {
    document.title = 'Listing Studio · Marketplaces'
  }, [])

  const selectedMarketplaceCount = useMemo(
    () => Object.values(selected).filter((set) => set.size > 0).length,
    [selected],
  )

  if (!subcategory) {
    return <Navigate to="/workspace/new" replace />
  }

  function toggleMarketplace(marketplace: Marketplace) {
    setSelected((current) => {
      const next = { ...current }
      const isOn = current[marketplace.id].size > 0
      next[marketplace.id] = isOn
        ? new Set()
        : new Set(marketplace.options.map((option) => option.id))
      return next
    })
  }

  function toggleOption(marketplaceId: string, optionId: string) {
    setSelected((current) => {
      const nextSet = new Set(current[marketplaceId])
      if (nextSet.has(optionId)) nextSet.delete(optionId)
      else nextSet.add(optionId)
      return { ...current, [marketplaceId]: nextSet }
    })
  }

  return (
    <BatchShell
      title={`New batch · ${subcategory} · ${SKU_COUNT} SKUs`}
      stepIndex={2}
      stepLabel="step 3 of 4"
      footer={
        <div className="batch-page__footer-actions">
          <button
            type="button"
            className="btn-outline"
            onClick={() => navigate('/workspace/new/validation')}
          >
            Back
          </button>
          <button type="button" className="btn-primary" disabled={selectedMarketplaceCount === 0}>
            Generate
          </button>
        </div>
      }
    >
      <h2 className="batch-page__heading">Where are these listings going?</h2>
      <p className="batch-page__lede">
        Each marketplace is generated separately, with its own content and its own asset types.
      </p>

      <div className="marketplace-list">
        {MARKETPLACES.map((marketplace) => {
          const selectedOptions = selected[marketplace.id]
          const isSelected = selectedOptions.size > 0
          return (
            <section
              key={marketplace.id}
              className={`marketplace-row${isSelected ? '' : ' marketplace-row--off'}`}
            >
              <button
                type="button"
                className="marketplace-row__toggle"
                onClick={() => toggleMarketplace(marketplace)}
              >
                <span className={`check${isSelected ? ' check--on' : ''}`} aria-hidden="true" />
                <span className="marketplace-row__name">{marketplace.name}</span>
                {!isSelected ? <span className="marketplace-row__badge">not selected</span> : null}
              </button>
              <div className="marketplace-row__options">
                {marketplace.options.map((option) => {
                  const optionOn = selectedOptions.has(option.id)
                  return (
                    <button
                      key={option.id}
                      type="button"
                      className={`marketplace-option${optionOn ? '' : ' marketplace-option--off'}`}
                      onClick={() => toggleOption(marketplace.id, option.id)}
                    >
                      <span className={`check${optionOn ? ' check--on' : ''}`} aria-hidden="true" />
                      <span>{option.label}</span>
                      {option.count != null ? <em>({option.count})</em> : null}
                    </button>
                  )
                })}
              </div>
            </section>
          )
        })}
      </div>

      <p className="marketplace-summary">
        <strong>{SKU_COUNT} SKUs</strong> × <strong>{selectedMarketplaceCount} marketplaces</strong>{' '}
        = <strong className="marketplace-summary__accent">{SKU_COUNT * selectedMarketplaceCount} listings</strong>
      </p>

      <div className="marketplace-notes">
        <div className="marketplace-note">
          <img src={iconLock} alt="" width={16} height={16} />
          <div>
            <p>
              <strong>This choice is fixed for the life of the batch.</strong>
            </p>
            <p>
              A marketplace can&apos;t be added later — launching somewhere new means a new batch.
              The content itself stays editable forever.
            </p>
          </div>
        </div>
        <div className="marketplace-note">
          <img src={iconInfo} alt="" width={16} height={16} />
          <p>
            Large batches take hours. You can close the tab — generation keeps running, and finished
            SKUs are workable while the rest are still queued.
          </p>
        </div>
      </div>
    </BatchShell>
  )
}

export default NewBatchMarketplaces
