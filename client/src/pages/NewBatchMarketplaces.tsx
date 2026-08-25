import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { MarketplaceSelectionMarketplace } from '../api/catalog'
import { createJob } from '../api/jobs'
import iconInfo from '../assets/icon-info.svg'
import iconLock from '../assets/icon-lock.svg'
import { useBatchUploadStore } from '../batch/batchUploadStore'
import { useMarketplaceSelectionStore } from '../batch/marketplaceSelectionStore'
import { useBrands } from '../brands/useBrands'
import BatchShell from '../components/BatchShell'
import { getBatchSubcategory } from '../data/batchDraft'

/** Derived attributes and the selections they need in the same job (mirrors server check). */
const ATTRIBUTE_DEPENDENCIES: Record<string, string[]> = {
  KEY_FEATURES: ['BULLET_POINTS', 'DESCRIPTION'],
}

/** Stable empty snapshot — `?? []` inline would allocate every getSnapshot and loop forever. */
const EMPTY_SKU_IMAGES: { sku_id: string }[] = []

function NewBatchMarketplaces() {
  const navigate = useNavigate()
  const subcategory = getBatchSubcategory()
  const { selectedBrand } = useBrands()
  const skuImages = useBatchUploadStore((state) => state.result?.skuImages ?? EMPTY_SKU_IMAGES)
  const skuCount = skuImages.length

  const status = useMarketplaceSelectionStore((state) => state.status)
  const marketplaces = useMarketplaceSelectionStore((state) => state.marketplaces)
  const ensureLoaded = useMarketplaceSelectionStore((state) => state.ensureLoaded)
  const reload = useMarketplaceSelectionStore((state) => state.reload)

  const [selected, setSelected] = useState<Record<string, Set<string>>>({})
  const [selectionSeed, setSelectionSeed] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  useEffect(() => {
    document.title = 'Listing Studio · Marketplaces'
  }, [])

  const draftMissing = !subcategory || skuCount === 0
  useEffect(() => {
    if (draftMissing) {
      navigate('/workspace/new', { replace: true })
    }
  }, [draftMissing, navigate])

  useEffect(() => {
    if (draftMissing) return
    void ensureLoaded()
  }, [draftMissing, ensureLoaded])

  const payloadKey =
    status === 'ready'
      ? marketplaces
          .map(
            (item) =>
              `${item.external_id}|${item.attributes.map((group) => group.id).join(',')}`,
          )
          .join(';')
      : null

  useEffect(() => {
    if (draftMissing || payloadKey == null || payloadKey === selectionSeed) return
    setSelectionSeed(payloadKey)
    setSelected(
      Object.fromEntries(
        marketplaces.map((marketplace) => [
          marketplace.external_id,
          new Set(marketplace.attributes.map((attribute) => attribute.id)),
        ]),
      ),
    )
  }, [draftMissing, payloadKey, selectionSeed, marketplaces])

  const selectedMarketplaceCount = useMemo(
    () => Object.values(selected).filter((set) => set.size > 0).length,
    [selected],
  )

  if (draftMissing) {
    return (
      <div className="app-loading">
        <p>Returning to start a new batch…</p>
      </div>
    )
  }

  const loading = status === 'idle' || status === 'loading'
  const loadFailed = status === 'error'

  function attributesForMarketplace(marketplace: MarketplaceSelectionMarketplace, groupIds: Set<string>) {
    const byExternalId = new Map<string, { attribute_external_id: string; quantity: number }>()
    for (const group of marketplace.attributes) {
      if (!groupIds.has(group.id)) continue
      for (const item of group.items) {
        byExternalId.set(item.external_id, {
          attribute_external_id: item.external_id,
          quantity: item.quantity,
        })
      }
    }
    return [...byExternalId.values()]
  }

  function toggleMarketplace(marketplace: MarketplaceSelectionMarketplace) {
    setSelected((current) => {
      const next = { ...current }
      const isOn = (current[marketplace.external_id]?.size ?? 0) > 0
      next[marketplace.external_id] = isOn
        ? new Set()
        : new Set(marketplace.attributes.map((attribute) => attribute.id))
      return next
    })
  }

  function toggleAttribute(marketplaceId: string, attributeId: string) {
    setSelected((current) => {
      const nextSet = new Set(current[marketplaceId] ?? [])
      if (nextSet.has(attributeId)) {
        nextSet.delete(attributeId)
        for (const [dependent, dependencies] of Object.entries(ATTRIBUTE_DEPENDENCIES)) {
          if (dependencies.includes(attributeId)) nextSet.delete(dependent)
        }
      } else {
        nextSet.add(attributeId)
        for (const dependency of ATTRIBUTE_DEPENDENCIES[attributeId] ?? []) {
          nextSet.add(dependency)
        }
      }
      return { ...current, [marketplaceId]: nextSet }
    })
  }

  async function handleGenerate() {
    const skuIds = skuImages.map((entry) => entry.sku_id)
    if (skuIds.length === 0 || selectedMarketplaceCount === 0 || !selectedBrand) return

    setSubmitting(true)
    setSubmitError(null)
    try {
      const marketplacesPayload = marketplaces.flatMap((marketplace) => {
        const groupIds = selected[marketplace.external_id] ?? new Set<string>()
        if (groupIds.size === 0) return []
        const attributes = attributesForMarketplace(marketplace, groupIds)
        if (attributes.length === 0) return []
        return [{ marketplace_external_id: marketplace.external_id, attributes }]
      })

      if (marketplacesPayload.length === 0) {
        setSubmitError('Select at least one marketplace and content type to generate.')
        return
      }

      const response = await createJob({
        sku_ids: skuIds,
        marketplaces: marketplacesPayload,
      })

      navigate(`/batches/preview/${response.job_group_id}`)
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
                  {marketplace.attributes.map((attribute) => {
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
