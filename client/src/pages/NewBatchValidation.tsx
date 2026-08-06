import { useEffect, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { getCategoryTemplate } from '../api/categories'
import iconArrowRight from '../assets/icon-arrow-right.svg'
import iconCheck from '../assets/icon-check.svg'
import iconCheckSm from '../assets/icon-check-sm.svg'
import iconError from '../assets/icon-error.svg'
import { useBatchUploadStore } from '../batch/batchUploadStore'
import BatchShell from '../components/BatchShell'
import { getBatchSubcategory, getBatchSubcategorySelection } from '../data/batchDraft'
import {
  validateBatchFiles,
  type ValidationIssue,
  type ValidationStep,
} from '../lib/validateBatchFiles'

function groupIssues(issues: ValidationIssue[]): Array<{
  title: ValidationIssue['group']
  hint: string
  items: ValidationIssue[]
}> {
  const order: Array<{ title: ValidationIssue['group']; hint: string }> = [
    { title: 'CSV', hint: 'Fix these in your spreadsheet.' },
    { title: 'CSV ↔ ZIP MAPPING', hint: 'Fix these by renaming folders or editing rows.' },
    { title: 'FILES', hint: 'File-level checks.' },
  ]

  return order
    .map((group) => ({
      ...group,
      items: issues.filter((issue) => issue.group === group.title),
    }))
    .filter((group) => group.items.length > 0)
}

function StepList({ steps }: { steps: ValidationStep[] }) {
  return (
    <ul className="validation-progress-list">
      {steps.map((step) => (
        <li
          key={step.id}
          className={`validation-progress-list__item validation-progress-list__item--${step.status}`}
        >
          <span className="validation-progress-list__mark" aria-hidden>
            {step.status === 'passed' ? (
              '✓'
            ) : step.status === 'failed' ? (
              '!'
            ) : step.status === 'running' ? (
              <span className="validation-progress-list__dots">
                <span />
                <span />
                <span />
              </span>
            ) : (
              '○'
            )}
          </span>
          <div>
            <p className="validation-progress-list__label">{step.label}</p>
            {step.detail ? (
              <p className="validation-progress-list__detail">{step.detail}</p>
            ) : null}
          </div>
        </li>
      ))}
    </ul>
  )
}

function NewBatchValidation() {
  const navigate = useNavigate()
  const subcategory = getBatchSubcategory()
  const selection = getBatchSubcategorySelection()
  const productFile = useBatchUploadStore((s) => s.productFile)
  const imagesFile = useBatchUploadStore((s) => s.imagesFile)
  const validating = useBatchUploadStore((s) => s.validating)
  const steps = useBatchUploadStore((s) => s.steps)
  const result = useBatchUploadStore((s) => s.result)
  const setValidating = useBatchUploadStore((s) => s.setValidating)
  const setSteps = useBatchUploadStore((s) => s.setSteps)
  const setResult = useBatchUploadStore((s) => s.setResult)
  const clearValidation = useBatchUploadStore((s) => s.clearValidation)
  const [runError, setRunError] = useState<string | null>(null)
  const [detailsOpen, setDetailsOpen] = useState(false)

  useEffect(() => {
    document.title = validating
      ? 'Listing Studio · Validating'
      : result && !result.passed
        ? 'Listing Studio · Validation problems'
        : 'Listing Studio · Validation'
  }, [validating, result])

  useEffect(() => {
    if (!productFile || !imagesFile || result) return

    let cancelled = false

    async function run() {
      setValidating(true)
      setRunError(null)

      try {
        const product = productFile
        const images = imagesFile
        if (!product || !images) return

        const mandatoryFields = selection?.external_id
          ? (await getCategoryTemplate(selection.external_id)).fields
          : []

        if (cancelled) return

        const next = await validateBatchFiles({
          productFile: product,
          imagesFile: images,
          mandatoryFields,
          onProgress: (nextSteps) => {
            if (!cancelled) setSteps(nextSteps)
          },
        })

        if (!cancelled) setResult(next)
      } catch (error) {
        if (!cancelled) {
          setValidating(false)
          setRunError(error instanceof Error ? error.message : 'Validation failed.')
        }
      }
    }

    void run()

    return () => {
      cancelled = true
    }
  }, [
    productFile,
    imagesFile,
    result,
    selection?.external_id,
    setValidating,
    setSteps,
    setResult,
  ])

  if (!subcategory) {
    return <Navigate to="/workspace/new" replace />
  }

  if (!productFile || !imagesFile) {
    return <Navigate to="/workspace/new/upload" replace />
  }

  const hasProblems = Boolean(result && !result.passed)
  const showProgress = validating || (!result && !runError)
  const failCount = result ? result.issues.filter((i) => !i.ok).length : 0
  const problemGroups = result ? groupIssues(result.issues.filter((issue) => !issue.ok)) : []
  const affectedCount = result?.problemSkus.length ?? 0

  const canUpload = Boolean(result && (result.skuImages?.length ?? 0) > 0)

  const footer = showProgress ? null : (
    <div className="batch-page__footer-actions">
      <button
        type="button"
        className="btn-outline"
        onClick={() => {
          clearValidation()
          navigate('/workspace/new/upload')
        }}
      >
        Re-upload files
      </button>
      <button
        type="button"
        className={canUpload ? 'btn-primary' : 'btn-muted btn-muted--continue'}
        disabled={!canUpload}
        onClick={() => {
          if (!canUpload) return
          useBatchUploadStore.getState().resetUpload()
          navigate('/workspace/new/uploading')
        }}
      >
        Upload to system
        <img src={iconArrowRight} alt="" width={16} height={16} />
      </button>
    </div>
  )

  return (
    <BatchShell
      title={`New batch · ${subcategory}`}
      stepIndex={1}
      stepLabel="step 2 of 4"
      bodyClassName={hasProblems ? 'batch-page__body batch-page__body--wide' : 'batch-page__body'}
      footer={footer}
    >
      <p className="section-kicker">Validation</p>

      {runError ? (
        <>
          <h2 className="batch-page__heading">Validation could not finish.</h2>
          <p className="batch-page__lede">{runError}</p>
          <button
            type="button"
            className="btn-primary"
            onClick={() => navigate('/workspace/new/upload')}
          >
            Back to upload
          </button>
        </>
      ) : null}

      {showProgress && !runError ? (
        <>
          <h2 className="batch-page__heading">Validating…</h2>
          <p className="batch-page__lede">
            Checking the flat file against the subcategory template and matching every sku_id to an
            images folder inside the ZIP root.
          </p>
          <StepList
            steps={
              steps.length > 0
                ? steps
                : [
                    { id: 'read_product', label: 'Reading product file', status: 'running' },
                    {
                      id: 'mandatory_columns',
                      label: 'Checking mandatory columns in the flat file',
                      status: 'pending',
                    },
                    {
                      id: 'read_images',
                      label: 'Reading images ZIP and SKU folders',
                      status: 'pending',
                    },
                    {
                      id: 'sku_mapping',
                      label: 'Matching every sku_id to a folder with at least one image',
                      status: 'pending',
                    },
                    { id: 'summary', label: 'Summarizing overall status', status: 'pending' },
                  ]
            }
          />
        </>
      ) : null}

      {result && !result.passed ? (
        <>
          <h2 className="batch-page__heading">
            {failCount === 1
              ? 'One thing needs fixing before this can run.'
              : `${failCount} things need fixing before this can run.`}
          </h2>
          <p className="batch-page__lede">
            {result.skuCount} SKUs in file · {result.validCount} valid · {affectedCount} with
            problems. Every SKU has to be valid — a partial batch would leave silent gaps in your
            catalogue.
          </p>

          <div className="validation-sku-summary">
            <p className="validation-sku-summary__label">
              {affectedCount === 1
                ? '1 SKU has problems'
                : affectedCount > 1
                  ? `${affectedCount} SKUs have problems`
                  : `${failCount} problems found`}
            </p>
            <button
              type="button"
              className="validation-sku-summary__toggle"
              onClick={() => setDetailsOpen((open) => !open)}
              aria-expanded={detailsOpen}
            >
              {detailsOpen ? 'Hide problem details' : 'View which SKUs have problems'}
            </button>
          </div>

          {detailsOpen ? (
            <div className="validation-details">
              {result.problemSkus.length > 0 ? (
                <div className="validation-sku-chips">
                  <p className="validation-sku-chips__label">Affected SKUs</p>
                  <div className="validation-sku-chips__list">
                    {result.problemSkus.map((sku) => (
                      <code key={sku}>{sku}</code>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="validation-groups">
                {problemGroups.map((group) => (
                  <section key={group.title} className="validation-group">
                    <div className="validation-group__head">
                      <h3>{group.title}</h3>
                      <p>{group.hint}</p>
                    </div>
                    <ul className="validation-group__list">
                      {group.items.map((item, index) => (
                        <li key={`${group.title}-${item.key}-${index}`}>
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
            </div>
          ) : null}

          <p className="batch-page__lede validation-footer-copy">
            Fix the issues and upload again — nothing else about your batch is lost.
          </p>
        </>
      ) : null}

      {result && result.passed ? (
        <>
          <div className="validation-success-title">
            <img src={iconCheck} alt="" width={24} height={24} />
            <h2 className="batch-page__heading">All good. {result.skuCount} SKUs ready.</h2>
          </div>

          <ul className="validation-success-list">
            {result.successItems.map((item) => (
              <li key={item}>
                <img src={iconCheckSm} alt="" width={16} height={16} />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </BatchShell>
  )
}

export default NewBatchValidation
