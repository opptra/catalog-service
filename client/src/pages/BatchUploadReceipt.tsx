import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import iconCsv from '../assets/icon-csv.svg'
import iconExport from '../assets/icon-export.svg'
import iconLockBanner from '../assets/icon-lock-banner.svg'
import iconWarning from '../assets/icon-warning.svg'
import iconZip from '../assets/icon-zip.svg'
import AppHeader from '../components/AppHeader'
import { useBrands } from '../brands/useBrands'

type ReceiptTab = 'content' | 'exports' | 'upload'

function BatchUploadReceipt() {
  const { selectedBrand: brand } = useBrands()
  const [tab, setTab] = useState<ReceiptTab>('upload')

  useEffect(() => {
    document.title = 'Listing Studio · Upload receipt'
  }, [])

  if (!brand) {
    return <Navigate to="/brands" replace />
  }

  return (
    <div className="page-shell">
      <AppHeader
        brandName={brand.name}
        showExecutionHistory
        onExecutionHistoryClick={() => {
          // Execution history UI — not wired to the backend yet.
        }}
      />

      <main className="receipt-page">
        <div className="receipt-header">
          <div className="receipt-header__main">
            <div className="receipt-header__top">
              <div>
                <h1 className="receipt-header__title">Summer Tees — core range</h1>
                <p className="receipt-header__meta">
                  Apparel — T-Shirts · 30 SKUs · Amazon + Flipkart
                  <span> · marketplaces fixed for this batch</span>
                </p>
              </div>
              <button type="button" className="btn-primary btn-primary--sm">
                <img src={iconExport} alt="" width={16} height={16} />
                Create export
              </button>
            </div>

            <div className="receipt-alerts">
              <p>
                <img src={iconWarning} alt="" width={12} height={12} />
                <strong>Amazon</strong> 2 changed since Export #2
              </p>
              <p>
                <img src={iconWarning} alt="" width={12} height={12} />
                <strong>Flipkart</strong> 1 changed since Export #2
              </p>
            </div>

            <div className="receipt-tabs" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={tab === 'content'}
                className={tab === 'content' ? 'receipt-tabs__tab receipt-tabs__tab--active' : 'receipt-tabs__tab'}
                onClick={() => setTab('content')}
              >
                Content
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === 'exports'}
                className={tab === 'exports' ? 'receipt-tabs__tab receipt-tabs__tab--active' : 'receipt-tabs__tab'}
                onClick={() => setTab('exports')}
              >
                Exports
                <span className="receipt-tabs__badge">2</span>
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === 'upload'}
                className={tab === 'upload' ? 'receipt-tabs__tab receipt-tabs__tab--active' : 'receipt-tabs__tab'}
                onClick={() => setTab('upload')}
              >
                Upload
              </button>
            </div>
          </div>
        </div>

        {tab === 'upload' ? (
          <div className="receipt-upload">
            <div className="receipt-banner">
              <img src={iconLockBanner} alt="" width={16} height={16} />
              <div>
                <p>
                  <strong>The source files are fixed for this batch.</strong>
                </p>
                <p>
                  SKUs can&apos;t be added or removed and source photos can&apos;t be swapped. To
                  change the inputs, start a new batch.
                </p>
              </div>
            </div>

            <div className="receipt-files">
              <div className="receipt-file">
                <img src={iconCsv} alt="" width={20} height={20} />
                <div>
                  <p className="receipt-file__label">Product data</p>
                  <p className="receipt-file__name">products.csv</p>
                </div>
                <span className="receipt-file__meta">14 KB · 30 rows</span>
              </div>
              <div className="receipt-file">
                <img src={iconZip} alt="" width={20} height={20} />
                <div>
                  <p className="receipt-file__label">Images</p>
                  <p className="receipt-file__name">images.zip</p>
                </div>
                <span className="receipt-file__meta">240 MB · 30 folders · 120 images</span>
              </div>
              <div className="receipt-file">
                <div className="receipt-file__spacer" />
                <div>
                  <p className="receipt-file__label">Subcategory template</p>
                  <p className="receipt-file__name">Apparel — T-Shirts</p>
                </div>
                <span className="receipt-file__meta">uploaded yesterday · 14 Jul · 10:20</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="receipt-placeholder">
            <p>{tab === 'content' ? 'Content' : 'Exports'} tab — UI only for now.</p>
          </div>
        )}
      </main>
    </div>
  )
}

export default BatchUploadReceipt
