import { useEffect, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import iconArrowRight from '../assets/icon-arrow-right.svg'
import iconCsv from '../assets/icon-csv.svg'
import iconLink from '../assets/icon-link.svg'
import iconZip from '../assets/icon-zip.svg'
import BatchShell from '../components/BatchShell'
import {
  getBatchFilesUploaded,
  getBatchSubcategory,
  setBatchFilesUploaded,
} from '../data/batchDraft'

function NewBatchUpload() {
  const navigate = useNavigate()
  const subcategory = getBatchSubcategory()
  const [filesUploaded, setFilesUploaded] = useState(getBatchFilesUploaded)

  useEffect(() => {
    document.title = 'Listing Studio · Upload'
  }, [])

  if (!subcategory) {
    return <Navigate to="/workspace/new" replace />
  }

  function markUploaded() {
    setBatchFilesUploaded(true)
    setFilesUploaded(true)
  }

  function clearUploaded() {
    setBatchFilesUploaded(false)
    setFilesUploaded(false)
  }

  return (
    <BatchShell
      title={`New batch · ${subcategory}`}
      stepIndex={1}
      stepLabel="step 2 of 4"
    >
      <h2 className="batch-page__heading">Upload your product data</h2>
      <p className="batch-page__lede">
        Two files, both mandatory. Every product row needs a matching image folder — that pairing is
        what validation checks hardest. Once generation starts, these files are fixed for the batch.
      </p>

      <div className="upload-grid">
        <div className={`upload-card${filesUploaded ? ' upload-card--ready' : ''}`}>
          <p className="upload-card__label">1 · Product data</p>
          <button type="button" className="upload-dropzone" onClick={markUploaded}>
            <img src={iconCsv} alt="" width={28} height={28} />
            <p className="upload-dropzone__text">
              Drop your file here or <span>browse</span>
            </p>
          </button>
          <p className="upload-card__hint">
            Allowed file types: CSV, XLS, XLSX
            <br />
            Must match the {subcategory} template. One row per SKU.
          </p>
        </div>

        <div className={`upload-card${filesUploaded ? ' upload-card--ready' : ''}`}>
          <p className="upload-card__label">2 · Images</p>
          <button type="button" className="upload-dropzone" onClick={markUploaded}>
            <img src={iconZip} alt="" width={28} height={28} />
            <p className="upload-dropzone__text">
              Drop your ZIP here or <span>browse</span>
            </p>
          </button>
          <p className="upload-card__hint">
            One folder per SKU, folder name = sku_id.
            <br />
            Minimum one image per folder.
          </p>
        </div>
      </div>

      <div className="expected-shape">
        <p className="expected-shape__label">Expected shape</p>
        <div className="expected-shape__grid">
          <div>
            <p className="expected-shape__file">products.csv</p>
            <div className="mini-table">
              <div className="mini-table__head">
                <span>sku_id</span>
                <span>name</span>
                <span>…</span>
              </div>
              {['SKU1', 'SKU2', 'SKU3'].map((sku) => (
                <div key={sku} className="mini-table__row">
                  <span className="mini-table__strong">{sku}</span>
                  <span>…</span>
                  <span>…</span>
                </div>
              ))}
            </div>
          </div>

          <div className="expected-shape__link">
            <img src={iconLink} alt="" width={16} height={16} />
            <span>1 : 1</span>
            <div className="expected-shape__rule" />
            <p>
              every row
              <br />
              needs a folder
            </p>
          </div>

          <div>
            <p className="expected-shape__file">images.zip</p>
            <div className="mini-table">
              <div className="mini-table__head mini-table__head--single">
                <span>folders</span>
              </div>
              <div className="mini-table__row mini-table__row--folders">
                <span className="mini-table__strong">/SKU1/</span>
                <span>a.jpg b.jpg</span>
              </div>
              <div className="mini-table__row mini-table__row--folders">
                <span className="mini-table__strong">/SKU2/</span>
                <span>a.jpg</span>
              </div>
              <div className="mini-table__row mini-table__row--folders">
                <span className="mini-table__strong">/SKU3/</span>
                <span>a.jpg b.jpg</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {filesUploaded ? (
        <div className="uploaded-panel">
          <p className="uploaded-panel__label">Uploaded</p>
          <div className="uploaded-panel__list">
            <div className="uploaded-panel__row">
              <span className="uploaded-panel__name">products.csv</span>
              <span className="uploaded-panel__status">uploaded</span>
              <span className="uploaded-panel__meta">14 KB</span>
              <button type="button" className="uploaded-panel__replace" onClick={clearUploaded}>
                Replace
              </button>
            </div>
            <div className="uploaded-panel__row">
              <span className="uploaded-panel__name">images.zip</span>
              <span className="uploaded-panel__status">uploaded</span>
              <span className="uploaded-panel__meta">240 MB</span>
              <button type="button" className="uploaded-panel__replace" onClick={clearUploaded}>
                Replace
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <div className="batch-page__footer-actions">
        <button
          type="button"
          className="btn-outline"
          onClick={() => navigate('/workspace/new')}
        >
          Back
        </button>
        <button
          type="button"
          className={filesUploaded ? 'btn-primary' : 'btn-muted btn-muted--continue'}
          disabled={!filesUploaded}
          onClick={() => navigate('/workspace/new/validation')}
        >
          Validate
          <img src={iconArrowRight} alt="" width={16} height={16} />
        </button>
      </div>
    </BatchShell>
  )
}

export default NewBatchUpload
