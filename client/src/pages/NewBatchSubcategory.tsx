import { useEffect, useId, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import iconArrowRight from '../assets/icon-arrow-right.svg'
import iconChevronDown from '../assets/icon-chevron-down.svg'
import iconDownload from '../assets/icon-download.svg'
import iconTemplate from '../assets/icon-template.svg'
import BatchShell from '../components/BatchShell'
import { setBatchSubcategory } from '../data/batchDraft'
import { getSelectedBrandId } from '../data/brands'

const SUBCATEGORIES = [
  'Sliders',
  'Running Shoes',
  'T-Shirts',
  'Bags',
  'Apparel',
] as const

function NewBatchSubcategory() {
  const navigate = useNavigate()
  const selectId = useId()
  const brandId = getSelectedBrandId()
  const [subcategory, setSubcategory] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const hasSelection = subcategory.length > 0

  useEffect(() => {
    document.title = 'Listing Studio · New batch'
  }, [])

  if (!brandId) {
    return <Navigate to="/brands" replace />
  }

  return (
    <BatchShell title="New batch" stepIndex={0} stepLabel="step 1 of 4" bodyClassName="batch-page__body">
      <h2 className="batch-page__heading">What are you generating for?</h2>
      <p className="batch-page__lede">
        The subcategory decides which CSV template your product data must match.
      </p>

      <div className="batch-select">
        <button
          type="button"
          id={selectId}
          className="batch-select__trigger"
          aria-haspopup="listbox"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span className={hasSelection ? 'batch-select__value' : 'batch-select__placeholder'}>
            {hasSelection ? subcategory : 'Choose a subcategory'}
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
          <ul className="batch-select__menu" role="listbox" aria-labelledby={selectId}>
            {SUBCATEGORIES.map((option) => (
              <li key={option} role="option" aria-selected={option === subcategory}>
                <button
                  type="button"
                  className="batch-select__option"
                  onClick={() => {
                    setSubcategory(option)
                    setMenuOpen(false)
                  }}
                >
                  {option}
                </button>
              </li>
            ))}
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
            Filling this template is the single best way to pass validation first time. Every field
            in it is mandatory.
          </p>
          <button type="button" className="btn-muted" disabled={!hasSelection}>
            <img src={iconDownload} alt="" width={16} height={16} />
            {hasSelection ? 'Download template' : 'select a subcategory first'}
          </button>
        </div>
      </div>

      <div className="batch-page__footer">
        <button
          type="button"
          className={hasSelection ? 'btn-primary' : 'btn-muted btn-muted--continue'}
          disabled={!hasSelection}
          onClick={() => {
            setBatchSubcategory(subcategory)
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
