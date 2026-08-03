import { useEffect } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import iconArrowRight from '../assets/icon-arrow-right.svg'
import iconCheck from '../assets/icon-check.svg'
import iconCheckSm from '../assets/icon-check-sm.svg'
import iconChevronRight from '../assets/icon-chevron-right-sm.svg'
import iconDownloadReport from '../assets/icon-download-report.svg'
import iconError from '../assets/icon-error.svg'
import iconReupload from '../assets/icon-reupload.svg'
import BatchShell from '../components/BatchShell'
import { getBatchSubcategory } from '../data/batchDraft'

const PROBLEM_GROUPS = [
  {
    title: 'CSV',
    hint: 'Fix these in your spreadsheet.',
    items: [
      { key: 'row 4', message: 'sku_id is empty', ok: false },
      { key: 'row 9', message: '“material” is required and blank', ok: false },
      { key: 'row 11', message: 'duplicate sku_id “SKU3”', ok: false },
    ],
  },
  {
    title: 'CSV ↔ ZIP MAPPING',
    hint: 'Fix these by renaming folders or editing rows.',
    items: [
      { key: 'SKU7', message: 'no folder named /SKU7/ in the zip', ok: false },
      { key: '/SKU9/', message: 'folder exists but contains 0 images', ok: false },
      { key: '/SKU12/', message: 'folder in zip has no matching row in the CSV', ok: false },
    ],
  },
  {
    title: 'FILES',
    hint: 'File-level checks.',
    items: [
      { key: 'CSV columns', message: 'match the running-shoes template', ok: true },
      { key: 'zip structure', message: 'readable', ok: true },
    ],
  },
] as const

const SUCCESS_ITEMS = [
  '12 rows · all mandatory fields present',
  '12 folders · every SKU has at least one image',
  '47 images total',
] as const

function NewBatchValidation() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const subcategory = getBatchSubcategory()
  const hasProblems = params.get('status') === 'problems'

  useEffect(() => {
    document.title = hasProblems
      ? 'Listing Studio · Validation problems'
      : 'Listing Studio · Validation'
  }, [hasProblems])

  if (!subcategory) {
    return <Navigate to="/workspace/new" replace />
  }

  return (
    <BatchShell
      title={`New batch · ${subcategory}`}
      stepIndex={1}
      stepLabel="step 2 of 4"
      bodyClassName={hasProblems ? 'batch-page__body batch-page__body--wide' : 'batch-page__body'}
    >
      <p className="section-kicker">Validation</p>

      {hasProblems ? (
        <>
          <h2 className="batch-page__heading">Three things need fixing before this can run.</h2>
          <p className="batch-page__lede">
            12 SKUs found · 9 valid · 3 with problems. Every SKU has to be valid — a partial batch
            would leave silent gaps in your catalogue.
          </p>

          <div className="validation-groups">
            {PROBLEM_GROUPS.map((group) => (
              <section key={group.title} className="validation-group">
                <div className="validation-group__head">
                  <h3>{group.title}</h3>
                  <p>{group.hint}</p>
                </div>
                <ul className="validation-group__list">
                  {group.items.map((item) => (
                    <li key={`${group.title}-${item.key}`}>
                      <img
                        src={item.ok ? iconCheckSm : iconError}
                        alt=""
                        width={16}
                        height={16}
                      />
                      <code>{item.key}</code>
                      <span className={item.ok ? 'validation-group__ok' : undefined}>
                        {item.message}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>

          <p className="batch-page__lede validation-footer-copy">
            Fix those 6 rows and upload again — nothing else about your batch is lost.
          </p>

          <div className="batch-page__footer-actions batch-page__footer-actions--start">
            <button type="button" className="btn-outline">
              <img src={iconDownloadReport} alt="" width={16} height={16} />
              Download report
            </button>
            <button
              type="button"
              className="btn-primary"
              onClick={() => navigate('/workspace/new/upload')}
            >
              <img src={iconReupload} alt="" width={16} height={16} />
              Re-upload files
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="validation-success-title">
            <img src={iconCheck} alt="" width={24} height={24} />
            <h2 className="batch-page__heading">All good. 12 SKUs ready.</h2>
          </div>

          <ul className="validation-success-list">
            {SUCCESS_ITEMS.map((item) => (
              <li key={item}>
                <img src={iconCheckSm} alt="" width={16} height={16} />
                <span>{item}</span>
              </li>
            ))}
          </ul>

          <button type="button" className="text-link">
            <img src={iconChevronRight} alt="" width={16} height={16} />
            view SKU list
          </button>

          <div className="batch-page__footer">
            <button
              type="button"
              className="btn-primary"
              onClick={() => navigate('/workspace/new/marketplaces')}
            >
              Continue
              <img src={iconArrowRight} alt="" width={16} height={16} />
            </button>
          </div>
        </>
      )}
    </BatchShell>
  )
}

export default NewBatchValidation
