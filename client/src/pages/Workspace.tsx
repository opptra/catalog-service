import { useEffect } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import AppHeader from '../components/AppHeader'
import { getBrandById, getSelectedBrandId } from '../data/brands'

function PlusIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M8 3.25V12.75M3.25 8H12.75"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  )
}

function Workspace() {
  const navigate = useNavigate()
  const brandId = getSelectedBrandId()
  const brand = brandId ? getBrandById(brandId) : undefined

  useEffect(() => {
    document.title = brand ? `Listing Studio · ${brand.name}` : 'Listing Studio'
  }, [brand])

  if (!brand) {
    return <Navigate to="/brands" replace />
  }

  return (
    <div className="page-shell">
      <AppHeader
        brandName={brand.name}
        showExecutionHistory
        onBrandClick={() => navigate('/brands')}
        onExecutionHistoryClick={() => {
          navigate('/workspace/batch/summer-tees')
        }}
      />
      <main className="workspace-page">
        <div className="workspace-empty">
          <h1 className="workspace-empty__title">Nothing here yet.</h1>
          <p className="workspace-empty__body">
            Start by uploading a product file and a folder of images. Everything else follows from
            there — and the batch stays yours to edit afterwards.
          </p>
          <button
            type="button"
            className="btn-primary"
            onClick={() => navigate('/workspace/new')}
          >
            <PlusIcon />
            New batch
          </button>
        </div>
      </main>
    </div>
  )
}

export default Workspace
