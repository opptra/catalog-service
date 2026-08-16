import { useEffect } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import iconArrowRight from '../assets/icon-arrow-right.svg'
import iconCheck from '../assets/icon-check.svg'
import {
  useBatchUploadStore,
  type UploadStatusStep,
} from '../batch/batchUploadStore'
import { useBrands } from '../brands/useBrands'
import BatchShell from '../components/BatchShell'
import { getBatchSubcategory, getBatchSubcategorySelection } from '../data/batchDraft'

function StatusList({ steps }: { steps: UploadStatusStep[] }) {
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

function NewBatchUploading() {
  const navigate = useNavigate()
  const { selectedBrand } = useBrands()
  const subcategory = getBatchSubcategory()
  const selection = getBatchSubcategorySelection()
  const productFile = useBatchUploadStore((s) => s.productFile)
  const imagesFile = useBatchUploadStore((s) => s.imagesFile)
  const result = useBatchUploadStore((s) => s.result)
  const uploadPhase = useBatchUploadStore((s) => s.uploadPhase)
  const uploadSteps = useBatchUploadStore((s) => s.uploadSteps)
  const uploadError = useBatchUploadStore((s) => s.uploadError)
  const startUpload = useBatchUploadStore((s) => s.startUpload)
  const resetUpload = useBatchUploadStore((s) => s.resetUpload)

  useEffect(() => {
    document.title =
      uploadPhase === 'done'
        ? 'Listing Studio · Upload complete'
        : 'Listing Studio · Uploading'
  }, [uploadPhase])

  useEffect(() => {
    if (!selectedBrand?.id) return
    if (!productFile || !imagesFile || !result || result.skuImages.length <= 0) return
    if (!selection?.external_id) return
    void startUpload(selectedBrand.id, selection.external_id)
  }, [
    selectedBrand?.id,
    productFile,
    imagesFile,
    result,
    selection?.external_id,
    startUpload,
  ])

  if (!selectedBrand?.id) {
    return <Navigate to="/brands" replace />
  }

  if (!subcategory || !selection?.external_id) {
    return <Navigate to="/workspace/new" replace />
  }

  if (!productFile || !imagesFile || !result || result.skuImages.length <= 0) {
    return <Navigate to="/workspace/new/validation" replace />
  }

  const isDone = uploadPhase === 'done'
  const isError = uploadPhase === 'error'

  const footer = isDone ? (
    <div className="batch-page__footer-actions">
      <button
        type="button"
        className="btn-outline"
        onClick={() => navigate('/workspace/new/validation')}
      >
        Back
      </button>
      <button
        type="button"
        className="btn-primary"
        onClick={() => navigate('/workspace/new/marketplaces')}
      >
        Continue
        <img src={iconArrowRight} alt="" width={16} height={16} />
      </button>
    </div>
  ) : isError ? (
    <div className="batch-page__footer-actions">
      <button
        type="button"
        className="btn-outline"
        onClick={() => navigate('/workspace/new/validation')}
      >
        Back
      </button>
      <button
        type="button"
        className="btn-primary"
        onClick={() => {
          resetUpload()
          void startUpload(selectedBrand.id, selection.external_id)
        }}
      >
        Try again
      </button>
    </div>
  ) : null

  return (
    <BatchShell
      title={`New batch · ${subcategory}`}
      stepIndex={1}
      stepLabel="step 2 of 4"
      footer={footer}
    >
      <p className="section-kicker">Upload</p>

      {isError ? (
        <>
          <h2 className="batch-page__heading">Upload could not finish.</h2>
          <p className="batch-page__lede">{uploadError ?? 'Something went wrong.'}</p>
        </>
      ) : null}

      {!isError && !isDone ? (
        <>
          <h2 className="batch-page__heading">Uploading…</h2>
          <p className="batch-page__lede">
            Transferring your validated product file and images into the catalog.
          </p>
          <StatusList steps={uploadSteps} />
        </>
      ) : null}

      {isDone ? (
        <>
          <div className="validation-success-title">
            <img src={iconCheck} alt="" width={24} height={24} />
            <h2 className="batch-page__heading">Upload complete.</h2>
          </div>
          <p className="batch-page__lede">
            {productFile.name} and {imagesFile.name} are ready. Next, choose marketplaces for this
            batch.
          </p>
          <StatusList steps={uploadSteps} />
        </>
      ) : null}
    </BatchShell>
  )
}

export default NewBatchUploading
