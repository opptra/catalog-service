import { useEffect, useId, useRef, useState, type DragEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import iconArrowRight from '../assets/icon-arrow-right.svg'
import iconCsv from '../assets/icon-csv.svg'
import iconLink from '../assets/icon-link.svg'
import iconZip from '../assets/icon-zip.svg'
import { useBatchUploadStore } from '../batch/batchUploadStore'
import BatchShell from '../components/BatchShell'
import { getBatchSubcategory, setBatchFilesUploaded } from '../data/batchDraft'

const PRODUCT_ACCEPT = '.csv,.xls,.xlsx,text/csv,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const IMAGES_ACCEPT = '.zip,application/zip,application/x-zip-compressed'

function isProductFile(file: File): boolean {
  const name = file.name.toLowerCase()
  return name.endsWith('.csv') || name.endsWith('.xls') || name.endsWith('.xlsx')
}

function isImagesFile(file: File): boolean {
  const name = file.name.toLowerCase()
  return name.endsWith('.zip') || file.type.includes('zip')
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function NewBatchUpload() {
  const navigate = useNavigate()
  const subcategory = getBatchSubcategory()
  const productInputId = useId()
  const imagesInputId = useId()
  const productInputRef = useRef<HTMLInputElement>(null)
  const imagesInputRef = useRef<HTMLInputElement>(null)
  const storedProduct = useBatchUploadStore((s) => s.productFile)
  const storedImages = useBatchUploadStore((s) => s.imagesFile)
  const setFiles = useBatchUploadStore((s) => s.setFiles)
  const clearValidation = useBatchUploadStore((s) => s.clearValidation)

  const [productFile, setProductFile] = useState<File | null>(storedProduct)
  const [imagesFile, setImagesFile] = useState<File | null>(storedImages)
  const [productDragging, setProductDragging] = useState(false)
  const [imagesDragging, setImagesDragging] = useState(false)

  const bothReady = productFile !== null && imagesFile !== null

  useEffect(() => {
    document.title = 'Listing Studio · Upload'
  }, [])

  useEffect(() => {
    setBatchFilesUploaded(bothReady)
  }, [bothReady])

  if (!subcategory) {
    return <Navigate to="/workspace/new" replace />
  }

  function takeProductFile(file: File | undefined) {
    if (!file || !isProductFile(file)) return
    clearValidation()
    setProductFile(file)
  }

  function takeImagesFile(file: File | undefined) {
    if (!file || !isImagesFile(file)) return
    clearValidation()
    setImagesFile(file)
  }

  function onProductDrop(event: DragEvent<HTMLButtonElement>) {
    event.preventDefault()
    setProductDragging(false)
    takeProductFile(event.dataTransfer.files[0])
  }

  function onImagesDrop(event: DragEvent<HTMLButtonElement>) {
    event.preventDefault()
    setImagesDragging(false)
    takeImagesFile(event.dataTransfer.files[0])
  }

  function startValidation() {
    if (!productFile || !imagesFile) return
    setFiles(productFile, imagesFile)
    navigate('/workspace/new/validation')
  }

  return (
    <BatchShell
      title={`New batch · ${subcategory}`}
      stepIndex={1}
      stepLabel="step 2 of 4"
      footer={
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
            className={bothReady ? 'btn-primary' : 'btn-muted btn-muted--continue'}
            disabled={!bothReady}
            onClick={startValidation}
          >
            Validate
            <img src={iconArrowRight} alt="" width={16} height={16} />
          </button>
        </div>
      }
    >
      <h2 className="batch-page__heading">Add your product files</h2>
      <p className="batch-page__lede">
        Two files, both mandatory. Select them here first — next you will validate the pairing, then
        upload into the batch. Every product row needs a matching image folder.
      </p>

      <div className="upload-grid">
        <div className={`upload-card${productFile ? ' upload-card--ready' : ''}`}>
          <p className="upload-card__label">1 · Product data</p>
          <input
            ref={productInputRef}
            id={productInputId}
            type="file"
            accept={PRODUCT_ACCEPT}
            hidden
            onChange={(event) => {
              takeProductFile(event.target.files?.[0])
              event.target.value = ''
            }}
          />
          <button
            type="button"
            className={`upload-dropzone${productDragging ? ' upload-dropzone--active' : ''}`}
            onClick={() => productInputRef.current?.click()}
            onDragEnter={(event) => {
              event.preventDefault()
              setProductDragging(true)
            }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={() => setProductDragging(false)}
            onDrop={onProductDrop}
          >
            <img src={iconCsv} alt="" width={28} height={28} />
            <p className="upload-dropzone__text">
              {productFile ? (
                <span>{productFile.name}</span>
              ) : (
                <>
                  Drop your file here or <span>browse</span>
                </>
              )}
            </p>
          </button>
          <p className="upload-card__hint">
            Allowed file types: CSV, XLS, XLSX
            <br />
            Must match the {subcategory} template. One row per SKU.
          </p>
        </div>

        <div className={`upload-card${imagesFile ? ' upload-card--ready' : ''}`}>
          <p className="upload-card__label">2 · Images</p>
          <input
            ref={imagesInputRef}
            id={imagesInputId}
            type="file"
            accept={IMAGES_ACCEPT}
            hidden
            onChange={(event) => {
              takeImagesFile(event.target.files?.[0])
              event.target.value = ''
            }}
          />
          <button
            type="button"
            className={`upload-dropzone${imagesDragging ? ' upload-dropzone--active' : ''}`}
            onClick={() => imagesInputRef.current?.click()}
            onDragEnter={(event) => {
              event.preventDefault()
              setImagesDragging(true)
            }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={() => setImagesDragging(false)}
            onDrop={onImagesDrop}
          >
            <img src={iconZip} alt="" width={28} height={28} />
            <p className="upload-dropzone__text">
              {imagesFile ? (
                <span>{imagesFile.name}</span>
              ) : (
                <>
                  Drop your ZIP here or <span>browse</span>
                </>
              )}
            </p>
          </button>
          <p className="upload-card__hint">
            ZIP with a root folder (any name). Inside it: one folder per SKU, folder name =
            SKU value.
            <br />
            Minimum one image per folder. Print CMYK JPEGs and TIFFs are converted
            to sRGB JPEG before upload so colors stay as they look on your computer.
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
                <span>SKU</span>
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
            <p className="expected-shape__file">images.zip → root → sku folders</p>
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

      {productFile || imagesFile ? (
        <div className="uploaded-panel">
          <p className="uploaded-panel__label">Selected</p>
          <div className="uploaded-panel__list">
            {productFile ? (
              <div className="uploaded-panel__row">
                <span className="uploaded-panel__name">{productFile.name}</span>
                <span className="uploaded-panel__status">ready</span>
                <span className="uploaded-panel__meta">{formatFileSize(productFile.size)}</span>
                <button
                  type="button"
                  className="uploaded-panel__replace"
                  onClick={() => productInputRef.current?.click()}
                >
                  Replace
                </button>
              </div>
            ) : null}
            {imagesFile ? (
              <div className="uploaded-panel__row">
                <span className="uploaded-panel__name">{imagesFile.name}</span>
                <span className="uploaded-panel__status">ready</span>
                <span className="uploaded-panel__meta">{formatFileSize(imagesFile.size)}</span>
                <button
                  type="button"
                  className="uploaded-panel__replace"
                  onClick={() => imagesInputRef.current?.click()}
                >
                  Replace
                </button>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </BatchShell>
  )
}

export default NewBatchUpload
