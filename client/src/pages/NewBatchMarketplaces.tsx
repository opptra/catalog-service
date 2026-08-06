import { useEffect, useMemo, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import type { MarketplaceSelectionMarketplace } from '../api/catalog'
import { createJob } from '../api/jobs'
import iconInfo from '../assets/icon-info.svg'
import iconLock from '../assets/icon-lock.svg'
import { useBatchUploadStore } from '../batch/batchUploadStore'
import { useMarketplaceSelectionStore } from '../batch/marketplaceSelectionStore'
import { useBrands } from '../brands/useBrands'
import BatchShell from '../components/BatchShell'
import { getBatchSubcategory } from '../data/batchDraft'

function NewBatchMarketplaces() {
  const navigate = useNavigate()
  const subcategory = getBatchSubcategory()
  const { selectedBrand } = useBrands()
  const skuImages = useBatchUploadStore((state) => state.result?.skuImages ?? [])
  const skuCount = skuImages.length

  const status = useMarketplaceSelectionStore((state) => state.status)
  const marketplaces = useMarketplaceSelectionStore((state) => state.marketplaces)
  const attributes = useMarketplaceSelectionStore((state) => state.attributes)
  const ensureLoaded = useMarketplaceSelectionStore((state) => state.ensureLoaded)
  const reload = useMarketplaceSelectionStore((state) => state.reload)

  const [selected, setSelected] = useState<Record<string, Set<string>>>({})
  const [selectionSeed, setSelectionSeed] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  useEffect(() => {
    document.title = 'Listing Studio · Marketplaces'
  }, [])

  useEffect(() => {
    void ensureLoaded()
  }, [ensureLoaded])

  // Seed checkbox state once per successful load payload (not on every render).
  const payloadKey =
    status === 'ready'
      ? `${marketplaces.map((item) => item.external_id).join(',')}|${attributes.map((item) => item.id).join(',')}`
      : null

  useEffect(() => {
    if (payloadKey == null || payloadKey === selectionSeed) return
    setSelectionSeed(payloadKey)
    const attributeIds = attributes.map((attribute) => attribute.id)
    setSelected(
      Object.fromEntries(
        marketplaces.map((marketplace) => [marketplace.external_id, new Set(attributeIds)]),
      ),
    )
  }, [payloadKey, selectionSeed, marketplaces, attributes])

  const selectedMarketplaceCount = useMemo(
    () => Object.values(selected).filter((set) => set.size > 0).length,
    [selected],
  )

  if (!subcategory) {
    return <Navigate to="/workspace/new" replace />
  }

  const loading = status === 'idle' || status === 'loading'
  const loadFailed = status === 'error'

  function toggleMarketplace(marketplace: MarketplaceSelectionMarketplace) {
    setSelected((current) => {
      const next = { ...current }
      const isOn = (current[marketplace.external_id]?.size ?? 0) > 0
      next[marketplace.external_id] = isOn
        ? new Set()
        : new Set(attributes.map((attribute) => attribute.id))
      return next
    })
  }

  function toggleAttribute(marketplaceId: string, attributeId: string) {
    setSelected((current) => {
      const nextSet = new Set(current[marketplaceId] ?? [])
      if (nextSet.has(attributeId)) nextSet.delete(attributeId)
      else nextSet.add(attributeId)
      return { ...current, [marketplaceId]: nextSet }
    })
  }

  function attributesForGroups(groupIds: Set<string>) {
    const byExternalId = new Map<string, { attribute_external_id: string; quantity: number }>()
    for (const group of attributes) {
      if (!groupIds.has(group.id)) continue
      for (const item of group.items) {
        byExternalId.set(item.external_id, {
          attribute_external_id: item.external_id,
          quantity: 1,
        })
      }
    }
    return [...byExternalId.values()]
  }

  async function handleGenerate() {
    const skuIds = skuImages.map((entry) => entry.sku_id)
    if (skuIds.length === 0 || selectedMarketplaceCount === 0 || !selectedBrand) return

    setSubmitting(true)
    setSubmitError(null)
    try {
      const requests = marketplaces.flatMap((marketplace) => {
        const groupIds = selected[marketplace.external_id]
        if (groupIds == null || groupIds.size === 0) return []
        const jobAttributes = attributesForGroups(groupIds)
        if (jobAttributes.length === 0) return []
        return [
          createJob({
            sku_ids: skuIds,
            brand_external_id: selectedBrand.id,
            marketplace_external_id: marketplace.external_id,
            attributes: jobAttributes,
          }),
        ]
      })
      await Promise.all(requests)
      navigate('/workspace/batch/summer-tees')
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : 'Could not start generation.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <BatchShell
      title={`New batch · ${subcategory} · ${skuCount} SKUs`}
      stepIndex={2}
      stepLabel="step 3 of 4"
      footer={
        <div className="batch-page__footer-actions">
          <button
            type="button"
            className="btn-outline"
            onClick={() => navigate('/workspace/new/validation')}
            disabled={submitting}
          >
            Back
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={
              selectedMarketplaceCount === 0 ||
              loading ||
              loadFailed ||
              submitting ||
              skuCount === 0 ||
              !selectedBrand
            }
            onClick={() => void handleGenerate()}
          >
            {submitting ? 'Starting…' : 'Generate'}
          </button>
        </div>
      }
    >
      <h2 className="batch-page__heading">Where are these listings going?</h2>
      <p className="batch-page__lede">
        Each marketplace is generated separately, with its own content and its own asset types.
      </p>

      {loading ? <p className="batch-select__status">Loading marketplaces…</p> : null}

      {loadFailed ? (
        <p className="batch-select__status">
          Couldn&apos;t load marketplaces.{' '}
          <button type="button" className="btn-outline" onClick={() => void reload()}>
            Try again
          </button>
        </p>
      ) : null}

      {submitError ? <p className="batch-select__status">{submitError}</p> : null}

      {!loading && !loadFailed && marketplaces.length === 0 ? (
        <p className="batch-select__status">No marketplaces available yet.</p>
      ) : null}

      {!loading && !loadFailed && marketplaces.length > 0 ? (
        <div className="marketplace-list">
          {marketplaces.map((marketplace) => {
            const selectedAttributes = selected[marketplace.external_id] ?? new Set<string>()
            const isSelected = selectedAttributes.size > 0
            return (
              <section
                key={marketplace.external_id}
                className={`marketplace-row${isSelected ? '' : ' marketplace-row--off'}`}
              >
                <button
                  type="button"
                  className="marketplace-row__toggle"
                  onClick={() => toggleMarketplace(marketplace)}
                >
                  <span className={`check${isSelected ? ' check--on' : ''}`} aria-hidden="true" />
                  <span className="marketplace-row__name">{marketplace.name}</span>
                  {!isSelected ? (
                    <span className="marketplace-row__badge">not selected</span>
                  ) : null}
                </button>
                <div className="marketplace-row__options">
                  {attributes.map((attribute) => {
                    const attributeOn = selectedAttributes.has(attribute.id)
                    return (
                      <button
                        key={attribute.id}
                        type="button"
                        className={`marketplace-option${attributeOn ? '' : ' marketplace-option--off'}`}
                        onClick={() => toggleAttribute(marketplace.external_id, attribute.id)}
                      >
                        <span
                          className={`check${attributeOn ? ' check--on' : ''}`}
                          aria-hidden="true"
                        />
                        <span>{attribute.label}</span>
                      </button>
                    )
                  })}
                </div>
              </section>
            )
          })}
        </div>
      ) : null}

      <p className="marketplace-summary">
        <strong>{skuCount} SKUs</strong> × <strong>{selectedMarketplaceCount} marketplaces</strong>{' '}
        ={' '}
        <strong className="marketplace-summary__accent">
          {skuCount * selectedMarketplaceCount} listings
        </strong>
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
