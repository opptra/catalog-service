import { useEffect, useState } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'
import axios from 'axios'
import {
  getJobGroupStatus,
  getSkuGenerationJobContent,
  getSkuImageDownload,
  retrySkuGenerationJob,
  type JobExpectedAttribute,
  type JobGroupStatusResponse,
  type JobStatusResponse,
  type MarketplaceAttributeConfig,
  type SkuGenerationJobAttributeSlot,
  type SkuGenerationJobContentResponse,
} from '../api/jobs'
import { useBrands } from '../brands/useBrands'
import ContentImageGrid from '../components/batch-content/ContentImageGrid'
import AttributeRegenModal, {
  type AttributeRegenTarget,
} from '../components/batch-content/AttributeRegenModal'
import ListingExportPanel from '../components/batch-content/ListingExportPanel'
import ProductImagesCarousel from '../components/batch-content/ProductImagesCarousel'
import SkuAttributesModal from '../components/batch-content/SkuAttributesModal'
import PipelineProgressBar from '../components/batch-content/PipelineProgressBar'
import AppHeader from '../components/AppHeader'
import type { ContentImage } from '../components/batch-content/types'
import { downloadSkuImagesZip } from '../lib/downloadSkuImagesZip'

const STATUS_POLL_MS = 4000
const CONTENT_POLL_MS = 5000

const PDP_IMAGE_NAMES = new Set(['IMAGE'])

function isTerminalStatus(status: string | undefined): boolean {
  return status === 'COMPLETED' || status === 'FAILED'
}

/** Prefer these labels; everything else is humanized from the enum name. */
const ATTRIBUTE_DISPLAY_LABELS: Record<string, string> = {
  A_PLUS: 'A+',
  BULLET_POINTS: 'Bullet points',
  DESCRIPTION: 'Description',
  TITLE: 'Title',
  ITEM_HIGHLIGHTS: 'Item highlights',
  KEY_FEATURES: 'Key features',
  BACKEND_KEYWORDS: 'Backend keywords',
  IMAGE: 'Gallery image',
}

/** Text attributes whose value is a JSON array of strings, rendered as a list. */
const LIST_TEXT_NAMES = new Set(['BULLET_POINTS', 'KEY_FEATURES'])

/** Shopper-reading order for text sections; names not listed keep API order after these. */
const TEXT_SECTION_ORDER = [
  'TITLE',
  'ITEM_HIGHLIGHTS',
  'BULLET_POINTS',
  'KEY_FEATURES',
  'DESCRIPTION',
  'BACKEND_KEYWORDS',
]

function textSectionRank(name: string): number {
  const index = TEXT_SECTION_ORDER.indexOf(name)
  return index === -1 ? TEXT_SECTION_ORDER.length : index
}

function textLimitsFromConfig(
  config?: MarketplaceAttributeConfig | null,
): { maxChars?: number; perItemMaxChars?: number } {
  const text = config?.text
  if (!text) return {}
  if (text.chars?.max != null) return { maxChars: text.chars.max }
  if (text.items?.chars?.max != null) return { perItemMaxChars: text.items.chars.max }
  return {}
}

function marketplaceHasListing(name: string | null | undefined): boolean {
  return (name ?? '').trim().toLowerCase() === 'amazon'
}

type ImageModalSource =
  | { kind: 'pdp'; index: number }
  | { kind: 'attribute'; attributeName: string; index: number }

function formatAttributeLabel(name: string): string {
  const known = ATTRIBUTE_DISPLAY_LABELS[name]
  if (known) return known
  const words = name.replaceAll('_', ' ').trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (words.length === 0) return name
  return words
    .map((word, index) => (index === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word))
    .join(' ')
}

function RefreshIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M13.5 2.5v3.5h-3.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M13.2 6A5.5 5.5 0 1 0 12.4 11.2"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
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

function slotsByName(
  attributes: SkuGenerationJobAttributeSlot[],
  name: string,
): SkuGenerationJobAttributeSlot[] {
  return attributes
    .filter((item) => item.name === name)
    .toSorted((a, b) => a.slot - b.slot)
}

function imageSlotsToGrid(
  attributes: SkuGenerationJobAttributeSlot[],
  names: Set<string>,
): ContentImage[] {
  return attributes
    .filter((item) => item.data_type === 'IMAGE' && names.has(item.name))
    .toSorted((a, b) => a.slot - b.slot || a.name.localeCompare(b.name))
    .map((slot) => ({
      id: `${slot.name}-${slot.slot}`,
      url: slot.value,
      label: `${formatAttributeLabel(slot.name)} ${slot.slot}`,
      valueExternalId: slot.value_external_id,
      version: slot.version,
      verification: slot.verification,
    }))
}

function parseBulletList(raw: string): string[] {
  try {
    const parsed: unknown = JSON.parse(raw)
    if (Array.isArray(parsed)) {
      return parsed.filter((item): item is string => typeof item === 'string')
    }
  } catch {
    // fall through
  }
  return raw
    .split(/\n|•/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function isAttributePending(
  name: string,
  tasks: Record<string, string> | undefined,
  skuStatus: string | undefined,
): boolean {
  if (tasks?.[name] === 'PENDING') return true
  return skuStatus === 'PENDING' && tasks?.[name] == null
}

function BatchContent() {
  const { jobExternalId: jobGroupId = '' } = useParams<{ jobExternalId: string }>()
  const { selectedBrand: brand } = useBrands()

  const [groupStatus, setGroupStatus] = useState<JobGroupStatusResponse | null>(null)
  const [activeMarketplaceExternalId, setActiveMarketplaceExternalId] = useState<string | null>(
    null,
  )
  const [statusError, setStatusError] = useState<string | null>(null)
  const [statusFetching, setStatusFetching] = useState(false)
  const [skuIndex, setSkuIndex] = useState(0)
  const [content, setContent] = useState<SkuGenerationJobContentResponse | null>(null)
  const [contentError, setContentError] = useState<string | null>(null)
  const [, setContentLoading] = useState(false)
  const [expandedText, setExpandedText] = useState<Record<string, boolean>>({})
  const [regenTarget, setRegenTarget] = useState<AttributeRegenTarget | null>(null)
  const [retrying, setRetrying] = useState(false)
  const [contentRefreshKey, setContentRefreshKey] = useState(0)
  const [imageDownloading, setImageDownloading] = useState(false)
  const [imageDownloadError, setImageDownloadError] = useState<string | null>(null)
  const [productImagesOpen, setProductImagesOpen] = useState(false)
  const [productAttributesOpen, setProductAttributesOpen] = useState(false)

  const status: JobStatusResponse | null = groupStatus?.active_job ?? null

  useEffect(() => {
    document.title = status
      ? `Listing Studio · ${status.category_name ?? 'Batch'}`
      : 'Listing Studio · Batch'
  }, [status])

  useEffect(() => {
    if (!jobGroupId) return
    let cancelled = false
    let intervalId: number | undefined

    async function loadStatus(): Promise<JobGroupStatusResponse | null> {
      setStatusFetching(true)
      try {
        const next = await getJobGroupStatus(
          jobGroupId,
          activeMarketplaceExternalId ?? undefined,
        )
        if (cancelled) return null
        setGroupStatus(next)
        if (activeMarketplaceExternalId == null && next.marketplaces.length > 0) {
          setActiveMarketplaceExternalId(next.marketplaces[0].marketplace_external_id)
        }
        setStatusError(null)
        return next
      } catch (error) {
        if (cancelled) return null
        setStatusError(error instanceof Error ? error.message : 'Could not load job status.')
        return null
      } finally {
        if (!cancelled) setStatusFetching(false)
      }
    }

    void loadStatus().then((next) => {
      if (cancelled || next == null || isTerminalStatus(next.status)) return
      intervalId = window.setInterval(() => {
        void loadStatus().then((polled) => {
          if (cancelled || polled == null || !isTerminalStatus(polled.status)) return
          if (intervalId != null) {
            window.clearInterval(intervalId)
            intervalId = undefined
          }
        })
      }, STATUS_POLL_MS)
    })

    return () => {
      cancelled = true
      if (intervalId != null) window.clearInterval(intervalId)
    }
  }, [jobGroupId, activeMarketplaceExternalId, contentRefreshKey])

  const skuJobs = status?.sku_generation_jobs ?? []
  const safeSkuIndex = Math.min(skuIndex, Math.max(skuJobs.length - 1, 0))
  const activeSkuJob = skuJobs[safeSkuIndex] ?? null
  const activeSkuJobId = activeSkuJob?.external_id ?? null

  useEffect(() => {
    if (!activeSkuJobId) {
      setContent(null)
      setContentLoading(false)
      return
    }
    const skuJobId = activeSkuJobId
    // Parent status already says this SKU is done — one fetch, no poll.
    const skuAlreadyDone = isTerminalStatus(activeSkuJob?.status)
    let cancelled = false
    let intervalId: number | undefined

    async function loadContent(showLoading: boolean): Promise<boolean> {
      if (showLoading) setContentLoading(true)
      try {
        const next = await getSkuGenerationJobContent(skuJobId)
        if (cancelled) return false
        setContent(next)
        setContentError(null)
        return (
          next.status === 'PENDING' ||
          Object.values(next.tasks ?? {}).some((task) => task === 'PENDING')
        )
      } catch (error) {
        if (cancelled) return false
        setContentError(error instanceof Error ? error.message : 'Could not load SKU content.')
        return false
      } finally {
        if (!cancelled && showLoading) setContentLoading(false)
      }
    }

    // Drop previous SKU content so next/prev always show shimmer first.
    setContent(null)
    setContentLoading(true)
    void loadContent(true).then((stillPending) => {
      if (cancelled || skuAlreadyDone || !stillPending) return
      intervalId = window.setInterval(() => {
        void loadContent(false).then((pending) => {
          if (cancelled || pending) return
          if (intervalId != null) {
            window.clearInterval(intervalId)
            intervalId = undefined
          }
        })
      }, CONTENT_POLL_MS)
    })

    return () => {
      cancelled = true
      if (intervalId != null) window.clearInterval(intervalId)
    }
    // Re-fetch when the selected SKU changes or a retry finishes. Terminal status is
    // read from the render that selected this SKU so completed jobs skip polling.
  }, [activeSkuJobId, contentRefreshKey])

  if (!brand) {
    return <Navigate to="/brands" replace />
  }

  if (!jobGroupId) {
    return <Navigate to="/workspace" replace />
  }

  const attributes = content?.attributes ?? []
  const expected = status?.expected_attributes ?? []
  const tasks = content?.tasks ?? activeSkuJob?.tasks
  const skuStatus = content?.status ?? activeSkuJob?.status
  // While switching SKUs / waiting for the content response, keep shimmer up.
  // Background polls keep the previous matching payload visible (no flash).
  const contentReady =
    content != null && activeSkuJobId != null && content.external_id === activeSkuJobId

  const textAttributes = expected
    .filter((item) => item.data_type === 'TEXT')
    .toSorted((a, b) => textSectionRank(a.name) - textSectionRank(b.name))
  const pdpExpected = expected.filter((item) => PDP_IMAGE_NAMES.has(item.name))
  const otherImageAttributes = expected.filter(
    (item) => item.data_type === 'IMAGE' && !PDP_IMAGE_NAMES.has(item.name),
  )

  const pdpImagesFromApi = contentReady
    ? imageSlotsToGrid(attributes, PDP_IMAGE_NAMES)
    : []
  const expectedPdpCount = pdpExpected.reduce((sum, item) => sum + item.quantity, 0)
  const pdpImages: ContentImage[] =
    pdpImagesFromApi.length > 0
      ? pdpImagesFromApi
      : Array.from({ length: expectedPdpCount }, (_, index) => ({
          id: `pdp-shimmer-${index}`,
          url: null,
          label: `Image ${index + 1}`,
        }))

  const otherImageGrids = otherImageAttributes.map((attr) => {
    const fromApi = contentReady ? imageSlotsToGrid(attributes, new Set([attr.name])) : []
    const images: ContentImage[] =
      fromApi.length > 0
        ? fromApi
        : Array.from({ length: attr.quantity }, (_, index) => ({
            id: `${attr.name}-shimmer-${index}`,
            url: null,
            label: `${formatAttributeLabel(attr.name)} ${index + 1}`,
          }))
    return { attribute: attr, images }
  })

  const otherImagesByName = new Map(
    otherImageGrids.map((grid) => [grid.attribute.name, grid.images]),
  )

  const activeMarketplace =
    groupStatus?.marketplaces.find(
      (item) => item.marketplace_external_id === activeMarketplaceExternalId,
    ) ?? groupStatus?.marketplaces[0] ??
    null

  const marketplaceName =
    content?.marketplace_name ?? status?.marketplace_name ?? activeMarketplace?.marketplace_name ?? 'Marketplace'

  const showListingExport =
    activeMarketplaceExternalId != null && marketplaceHasListing(activeMarketplace?.marketplace_name)

  const skuIdForDownload = activeSkuJob?.sku_id ?? content?.sku_id ?? null

  const isFirstSku = safeSkuIndex <= 0
  const isLastSku = skuJobs.length === 0 || safeSkuIndex >= skuJobs.length - 1

  function goSku(next: number) {
    if (skuJobs.length === 0 || next < 0 || next >= skuJobs.length) return
    setSkuIndex(next)
    setExpandedText({})
    setRegenTarget(null)
    setProductImagesOpen(false)
    setProductAttributesOpen(false)
    setContent(null)
    setContentLoading(true)
    setContentError(null)
  }

  function buildImageRegenTarget(
    source: ImageModalSource,
    index: number,
  ): AttributeRegenTarget | null {
    const images =
      source.kind === 'pdp' ? pdpImages : (otherImagesByName.get(source.attributeName) ?? [])
    const image = images[index]
    if (image?.url == null || image.valueExternalId == null || image.version == null) {
      return null
    }
    const kindLabel =
      source.kind === 'pdp' ? 'PDP' : formatAttributeLabel(source.attributeName)
    return {
      dataType: 'IMAGE',
      label: image.label,
      headerLabel: `SKU${safeSkuIndex + 1} · ${marketplaceName} · ${kindLabel} ${index + 1} of ${images.length}`,
      valueExternalId: image.valueExternalId,
      version: image.version,
      value: image.url,
      verification: image.verification ?? null,
      canPrev: index > 0 && Boolean(images[index - 1]?.url),
      canNext: index < images.length - 1 && Boolean(images[index + 1]?.url),
      onPrev: () => {
        const next = buildImageRegenTarget(source, index - 1)
        if (next) setRegenTarget(next)
      },
      onNext: () => {
        const next = buildImageRegenTarget(source, index + 1)
        if (next) setRegenTarget(next)
      },
    }
  }

  function openPdpImage(index: number) {
    const target = buildImageRegenTarget({ kind: 'pdp', index }, index)
    if (target) setRegenTarget(target)
  }

  function openAttributeImage(attributeName: string, index: number) {
    const target = buildImageRegenTarget({ kind: 'attribute', attributeName, index }, index)
    if (target) setRegenTarget(target)
  }

  async function refreshActiveSkuContent() {
    if (!activeSkuJobId) return
    try {
      const next = await getSkuGenerationJobContent(activeSkuJobId)
      setContent(next)
      setContentError(null)
    } catch (error) {
      setContentError(error instanceof Error ? error.message : 'Could not load SKU content.')
    }
  }

  function openTextRegen(attr: JobExpectedAttribute, slot: SkuGenerationJobAttributeSlot) {
    if (!slot.value || !slot.value_external_id || slot.version == null) return
    const label = formatAttributeLabel(attr.name)
    setRegenTarget({
      dataType: 'TEXT',
      label,
      headerLabel: `SKU${safeSkuIndex + 1} · ${marketplaceName} · ${label}`,
      valueExternalId: slot.value_external_id,
      version: slot.version,
      value: slot.value,
    })
  }

  async function handleRetry() {
    if (!activeSkuJobId || retrying) return
    setRetrying(true)
    setContentError(null)
    try {
      await retrySkuGenerationJob(activeSkuJobId)
    } catch (error) {
      // 409 = already retrying / still running; other errors surface as-is.
      setContentError(
        error instanceof Error ? error.message : 'Retry failed — try again shortly.',
      )
    } finally {
      setRetrying(false)
      setContentRefreshKey((current) => current + 1)
    }
  }

  async function handleImageDownload() {
    if (!jobGroupId || !skuIdForDownload || imageDownloading) {
      return
    }
    setImageDownloading(true)
    setImageDownloadError(null)
    try {
      const payload = await getSkuImageDownload(jobGroupId, skuIdForDownload)
      await downloadSkuImagesZip(payload)
    } catch (error) {
      let message = 'Could not download images. Please try again.'
      if (axios.isAxiosError(error)) {
        const detail = error.response?.data?.detail
        if (typeof detail === 'string' && detail.trim()) message = detail
        else if (error.message) message = error.message
      } else if (error instanceof Error && error.message) {
        message = error.message
      }
      setImageDownloadError(message)
    } finally {
      setImageDownloading(false)
    }
  }

  function renderTextSection(attr: JobExpectedAttribute) {
    const slot = contentReady ? slotsByName(attributes, attr.name)[0] : undefined
    const rawValue = slot?.value ?? null
    const pending =
      !contentReady || (isAttributePending(attr.name, tasks, skuStatus) && !rawValue)
    const label = formatAttributeLabel(attr.name)
    const isList = LIST_TEXT_NAMES.has(attr.name)
    const isBackendKeywords = attr.name === 'BACKEND_KEYWORDS'
    const listItems =
      (isList || isBackendKeywords) && rawValue ? parseBulletList(rawValue) : []
    const expanded = expandedText[attr.name] === true
    const canRegen =
      slot?.value_external_id != null && slot.version != null && Boolean(slot.value)

    const limit = textLimitsFromConfig(attr.config)
    let counter: string | null = null
    let overLimit = false
    if (rawValue && limit?.maxChars != null) {
      counter = `${rawValue.length} / ${limit.maxChars}`
      overLimit = rawValue.length > limit.maxChars
    }

    const keywordTerms = isBackendKeywords ? listItems : []

    return (
      <section key={attr.attribute_external_id} className="content-section">
        <div className="content-section__head">
          <h3 className="content-section__label">{label}</h3>
          {!pending && counter ? (
            <span
              className={`content-counter${overLimit ? ' content-counter--over' : ''}`}
            >
              {counter}
            </span>
          ) : null}
        </div>
        {pending ? (
          <div
            className={`content-shimmer ${isList ? 'content-shimmer--bullets' : attr.name === 'DESCRIPTION' ? 'content-shimmer--body' : 'content-shimmer--title'}`}
            aria-hidden="true"
          />
        ) : isBackendKeywords ? (
          <>
            <p className="content-section__note">
              Not shown to shoppers — indexed for search only.
            </p>
            <div className="content-keyword-chips">
              {keywordTerms.map((term, index) => (
                <span key={`${term}-${index}`} className="content-keyword-chip">
                  {term}
                </span>
              ))}
            </div>
          </>
        ) : isList ? (
          <ul className="content-bullets">
            {listItems.map((item, index) => (
              <li key={`${index}-${item.slice(0, 24)}`}>
                {item}
                {limit?.perItemMaxChars != null ? (
                  <span
                    className={`content-counter content-counter--inline${item.length > limit.perItemMaxChars ? ' content-counter--over' : ''}`}
                  >
                    {item.length}/{limit.perItemMaxChars}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p
            className={
              attr.name === 'TITLE'
                ? 'content-section__title-text'
                : `content-section__body-text${expanded || attr.name !== 'DESCRIPTION' ? '' : ' content-section__body-text--clamp'}`
            }
          >
            {rawValue ?? '—'}
          </p>
        )}
        {!pending ? (
          <div className="content-section__actions">
            {attr.name === 'DESCRIPTION' && rawValue ? (
              <button
                type="button"
                className="content-section__show-full"
                onClick={() =>
                  setExpandedText((current) => ({
                    ...current,
                    [attr.name]: !current[attr.name],
                  }))
                }
              >
                {expanded ? 'show less' : 'show full'}
              </button>
            ) : null}
            {!canRegen && tasks?.[attr.name] === 'FAILED' ? (
              <button
                type="button"
                className="content-regen"
                title="Re-run the failed generation for this SKU"
                disabled={retrying}
                onClick={() => void handleRetry()}
              >
                <RefreshIcon />
                {retrying ? 'Retrying…' : 'Retry'}
              </button>
            ) : (
              <button
                type="button"
                className="content-regen"
                title={canRegen ? 'Regenerate' : 'Regenerate unavailable'}
                disabled={!canRegen}
                onClick={() => {
                  if (slot) openTextRegen(attr, slot)
                }}
              >
                <RefreshIcon />
                Regenerate
              </button>
            )}
          </div>
        ) : null}
      </section>
    )
  }

  const titleText = status
    ? `${status.category_name ?? 'Batch'} · ${new Date(status.started_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}`
    : 'Loading batch…'

  return (
    <div className="page-shell page-shell--fixed">
      <AppHeader brandName={brand.name} showExecutionHistory />

      <main className="batch-content">
        <div className="batch-content__inner">
          {status ? (
            <PipelineProgressBar
              startedAt={groupStatus?.started_at ?? status.started_at}
              updatedAt={groupStatus?.updated_at ?? status.updated_at}
              jobStatus={groupStatus?.status ?? status.status}
              completedCount={groupStatus?.completed_sku_count ?? status.completed_sku_count}
              totalCount={groupStatus?.sku_count ?? status.sku_count}
              isFetching={statusFetching}
            />
          ) : (
            <div className="pipeline-progress pipeline-progress--loading">
              <p className="pipeline-progress__timing">Loading pipeline status…</p>
              <div className="pipeline-progress__track">
                <div className="pipeline-progress__fill pipeline-progress__fill--indeterminate" />
              </div>
            </div>
          )}

          {statusError ? <p className="batch-content__error">{statusError}</p> : null}

          <header className="batch-content__hero">
            <div className="batch-content__hero-text">
              <h1 className="batch-content__title">{titleText}</h1>
              <p className="batch-content__meta">
                <span>{status?.category_name ?? '—'}</span>
                <span className="batch-content__dot">·</span>
                <span>
                  {status?.sku_count ?? 0} SKUs · {marketplaceName}
                </span>
              </p>
            </div>
          </header>

          {showListingExport && activeMarketplaceExternalId ? (
            <ListingExportPanel
              key={`${jobGroupId}-${activeMarketplaceExternalId}`}
              jobGroupId={jobGroupId}
              marketplaceExternalId={activeMarketplaceExternalId}
              marketplaceName={activeMarketplace?.marketplace_name ?? 'Marketplace'}
              enabled={(groupStatus?.status ?? status?.status) === 'COMPLETED'}
            />
          ) : null}

          <nav className="batch-content__tabs" aria-label="Batch sections">
            <span className="batch-content__tab batch-content__tab--active">Content</span>
          </nav>

          <div className="batch-content__marketplaces">
            <div className="batch-content__mp-tabs" role="tablist" aria-label="Marketplaces">
              {(groupStatus?.marketplaces ?? []).map((marketplace) => {
                const active =
                  marketplace.marketplace_external_id === activeMarketplaceExternalId
                return (
                  <button
                    key={marketplace.marketplace_external_id}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    className={
                      active
                        ? 'batch-content__mp-tab batch-content__mp-tab--active'
                        : 'batch-content__mp-tab'
                    }
                    onClick={() => {
                      if (active) return
                      setActiveMarketplaceExternalId(marketplace.marketplace_external_id)
                      setSkuIndex(0)
                      setContent(null)
                      setExpandedText({})
                      setRegenTarget(null)
                      setProductImagesOpen(false)
                      setProductAttributesOpen(false)
                      setImageDownloadError(null)
                    }}
                  >
                    {marketplace.marketplace_name}
                  </button>
                )
              })}
            </div>
          </div>

          {imageDownloadError ? (
            <p className="batch-content__error">{imageDownloadError}</p>
          ) : null}

          <div className="batch-content__sku-bar">
            <div className="batch-content__sku-label">
              <span className="batch-content__sku-count">
                SKU {skuJobs.length === 0 ? 0 : safeSkuIndex + 1} of {skuJobs.length}
              </span>
              <span className="batch-content__sku-name">
                {content?.display_name ?? activeSkuJob?.display_name ?? activeSkuJob?.sku_id ?? '—'}
              </span>
            </div>
          </div>

          {contentError ? <p className="batch-content__error">{contentError}</p> : null}

          <div className="batch-content__body">
            {textAttributes.map((attr) => renderTextSection(attr))}

            {pdpImages.length > 0 ? (
              <ContentImageGrid
                title={`PDP images · ${pdpImages.length}`}
                hint="click image to view or regenerate"
                images={pdpImages}
                onSelect={openPdpImage}
              />
            ) : null}

            {otherImageGrids.map(({ attribute, images }) =>
              images.length > 0 ? (
                <ContentImageGrid
                  key={attribute.attribute_external_id}
                  title={`${formatAttributeLabel(attribute.name)} · ${images.length}`}
                  hint="click image to view or regenerate"
                  images={images}
                  onSelect={(index) => openAttributeImage(attribute.name, index)}
                />
              ) : null,
            )}
          </div>
        </div>
      </main>

      <footer className="batch-content__sku-dock">
        <div className="batch-content__sku-dock-inner">
          <div className="batch-content__sku-dock-copy">
            <span className="batch-content__sku-dock-count">
              SKU {skuJobs.length === 0 ? 0 : safeSkuIndex + 1} of {skuJobs.length}
            </span>
            <span className="batch-content__sku-dock-name">
              {content?.display_name ?? activeSkuJob?.display_name ?? activeSkuJob?.sku_id ?? '—'}
            </span>
          </div>
          <div className="batch-content__sku-dock-nav">
            <button
              type="button"
              className="btn-outline batch-content__sku-dock-btn"
              disabled={!skuIdForDownload || imageDownloading}
              onClick={() => void handleImageDownload()}
            >
              {imageDownloading ? 'Preparing…' : 'Download images'}
            </button>
            <button
              type="button"
              className="btn-outline batch-content__sku-dock-btn"
              disabled={activeSkuJobId == null}
              onClick={() => {
                setRegenTarget(null)
                setProductImagesOpen(false)
                setProductAttributesOpen(true)
              }}
            >
              View attributes
            </button>
            <button
              type="button"
              className="btn-outline batch-content__sku-dock-btn"
              disabled={activeSkuJobId == null}
              onClick={() => {
                setRegenTarget(null)
                setProductAttributesOpen(false)
                setProductImagesOpen(true)
              }}
            >
              View input images
            </button>
            <button
              type="button"
              className="btn-outline batch-content__sku-dock-btn"
              onClick={() => goSku(safeSkuIndex - 1)}
              disabled={isFirstSku}
              aria-disabled={isFirstSku}
            >
              <ChevronLeftIcon />
              Previous
            </button>
            <button
              type="button"
              className="btn-outline batch-content__sku-dock-btn"
              onClick={() => goSku(safeSkuIndex + 1)}
              disabled={isLastSku}
              aria-disabled={isLastSku}
            >
              Next
              <ChevronRightIcon />
            </button>
          </div>
        </div>
      </footer>

      <AttributeRegenModal
        open={regenTarget != null}
        target={regenTarget}
        onClose={() => setRegenTarget(null)}
        onApplied={() => {
          void refreshActiveSkuContent()
        }}
      />

      <ProductImagesCarousel
        open={productImagesOpen}
        skuGenerationJobExternalId={activeSkuJobId}
        skuLabel={
          content?.display_name ?? activeSkuJob?.display_name ?? activeSkuJob?.sku_id ?? 'SKU'
        }
        onClose={() => setProductImagesOpen(false)}
      />

      <SkuAttributesModal
        open={productAttributesOpen}
        skuGenerationJobExternalId={activeSkuJobId}
        skuLabel={
          content?.display_name ?? activeSkuJob?.display_name ?? activeSkuJob?.sku_id ?? 'SKU'
        }
        onClose={() => setProductAttributesOpen(false)}
      />

      <span className="visually-hidden">
        <Link to="/workspace">Back to workspace</Link>
      </span>
    </div>
  )
}

export default BatchContent
