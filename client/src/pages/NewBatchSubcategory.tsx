import { useEffect, useId, useRef, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import {
  getCategoryTemplate,
  listLeafCategories,
  type LeafCategory,
} from '../api/categories'
import { useBrands } from '../brands/useBrands'
import iconArrowRight from '../assets/icon-arrow-right.svg'
import iconChevronDown from '../assets/icon-chevron-down.svg'
import iconDownload from '../assets/icon-download.svg'
import iconTemplate from '../assets/icon-template.svg'
import BatchShell from '../components/BatchShell'
import { setBatchSubcategory } from '../data/batchDraft'
import { downloadCategoryTemplate } from '../lib/downloadCategoryTemplate'

function formatPathPrefix(path: LeafCategory['path']): string {
  if (path.length <= 1) return ''
  return path
    .slice(0, -1)
    .map((node) => node.name)
    .join(' › ')
}

function NewBatchSubcategory() {
  const navigate = useNavigate()
  const selectId = useId()
  const { selectedBrand } = useBrands()
  const [selected, setSelected] = useState<LeafCategory | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [options, setOptions] = useState<LeafCategory[]>([])
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(true)
  const [loading, setLoading] = useState(false)
  const [loadFailed, setLoadFailed] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const menuRef = useRef<HTMLUListElement>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const loadingRef = useRef(false)

  const hasSelection = selected !== null

  useEffect(() => {
    document.title = 'Listing Studio · New batch'
  }, [])

  useEffect(() => {
    if (!menuOpen) return

    function onPointerDown(event: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setMenuOpen(false)
      }
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setMenuOpen(false)
    }

    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [menuOpen])

  async function loadPage(nextOffset: number, replace: boolean) {
    if (loadingRef.current) return
    loadingRef.current = true
    setLoading(true)
    setLoadFailed(false)

    try {
      const page = await listLeafCategories(nextOffset)
      setOptions((current) => (replace ? page.items : [...current, ...page.items]))
      setOffset(nextOffset + page.items.length)
      setHasMore(page.has_more)
    } catch {
      setLoadFailed(true)
    } finally {
      loadingRef.current = false
      setLoading(false)
    }
  }

  function openMenu() {
    const opening = !menuOpen
    setMenuOpen(opening)
    if (opening && options.length === 0 && !loadingRef.current) {
      void loadPage(0, true)
    }
  }

  function handleMenuScroll() {
    const menu = menuRef.current
    if (!menu || !hasMore || loadingRef.current || loadFailed) return
    const nearBottom = menu.scrollTop + menu.clientHeight >= menu.scrollHeight - 48
    if (nearBottom) {
      void loadPage(offset, false)
    }
  }

  async function handleDownloadTemplate() {
    if (!selected || downloading) return
    setDownloading(true)
    setDownloadError(null)
    try {
      const template = await getCategoryTemplate(selected.external_id)
      await downloadCategoryTemplate(template)
    } catch {
      setDownloadError('Could not download the template. Please try again.')
    } finally {
      setDownloading(false)
    }
  }

  if (!selectedBrand) {
    return <Navigate to="/brands" replace />
  }

  return (
    <BatchShell title="New batch" stepIndex={0} stepLabel="step 1 of 4" bodyClassName="batch-page__body">
      <h2 className="batch-page__heading">What are you generating for?</h2>
      <p className="batch-page__lede">
        The subcategory decides which CSV template your product data must match.
      </p>

      <div className="batch-select" ref={rootRef}>
        <button
          type="button"
          id={selectId}
          className="batch-select__trigger"
          aria-haspopup="listbox"
          aria-expanded={menuOpen}
          onClick={openMenu}
        >
          <span className={hasSelection ? 'batch-select__value' : 'batch-select__placeholder'}>
            {hasSelection && selected ? (
              <>
                {selected.path.length > 1 ? (
                  <span className="batch-select__path">{formatPathPrefix(selected.path)} › </span>
                ) : null}
                <span className="batch-select__leaf">{selected.name}</span>
              </>
            ) : (
              'Choose a subcategory'
            )}
          </span>
          <img
            src={iconChevronDown}
            alt=""
            className="batch-select__chevron"
            width={16}
            height={16}
          />
        </button>
        {menuOpen ? (
          <ul
            className="batch-select__menu"
            role="listbox"
            aria-labelledby={selectId}
            ref={menuRef}
            onScroll={handleMenuScroll}
          >
            {options.map((option) => {
              const pathPrefix = formatPathPrefix(option.path)
              const isSelected = selected?.external_id === option.external_id
              return (
                <li key={option.external_id} role="option" aria-selected={isSelected}>
                  <button
                    type="button"
                    className="batch-select__option"
                    onClick={() => {
                      setSelected(option)
                      setMenuOpen(false)
                    }}
                  >
                    {pathPrefix ? <span className="batch-select__path">{pathPrefix} › </span> : null}
                    <span className="batch-select__leaf">{option.name}</span>
                  </button>
                </li>
              )
            })}
            {loading ? (
              <li className="batch-select__status" aria-live="polite">
                Loading categories…
              </li>
            ) : null}
            {loadFailed ? (
              <li className="batch-select__status">
                Couldn&apos;t load categories.{' '}
                <button
                  type="button"
                  className="batch-select__retry"
                  onClick={() => void loadPage(offset === 0 && options.length === 0 ? 0 : offset, options.length === 0)}
                >
                  Try again
                </button>
              </li>
            ) : null}
            {!loading && !loadFailed && options.length === 0 ? (
              <li className="batch-select__status">No subcategories available yet.</li>
            ) : null}
            {!loading && !loadFailed && !hasMore && options.length > 0 ? (
              <li className="batch-select__status batch-select__status--end">
                Showing {options.length} subcategor{options.length === 1 ? 'y' : 'ies'}
              </li>
            ) : null}
          </ul>
        ) : null}
      </div>

      <div className="batch-template-card">
        <img
          src={iconTemplate}
          alt=""
          className="batch-template-card__icon"
          width={20}
          height={20}
        />
        <div className="batch-template-card__content">
          <h3 className="batch-template-card__title">Download the subcategory template</h3>
          <p className="batch-template-card__body">
            Headers are color-coded in the file: red columns are mandatory, green columns are
            optional. Fill one row per SKU before uploading.
          </p>
          <button
            type="button"
            className="btn-muted"
            disabled={!hasSelection || downloading}
            onClick={() => void handleDownloadTemplate()}
          >
            <img src={iconDownload} alt="" width={16} height={16} />
            {!hasSelection
              ? 'select a subcategory first'
              : downloading
                ? 'Preparing template…'
                : 'Download template'}
          </button>
          {downloadError ? <p className="batch-template-card__error">{downloadError}</p> : null}
        </div>
      </div>

      <div className="batch-page__footer">
        <button
          type="button"
          className={hasSelection ? 'btn-primary' : 'btn-muted btn-muted--continue'}
          disabled={!hasSelection || !selected}
          onClick={() => {
            if (!selected) return
            setBatchSubcategory({
              external_id: selected.external_id,
              name: selected.name,
            })
            navigate('/workspace/new/upload')
          }}
        >
          Continue
          <img src={iconArrowRight} alt="" width={16} height={16} />
        </button>
      </div>
    </BatchShell>
  )
}

export default NewBatchSubcategory
