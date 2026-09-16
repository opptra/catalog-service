import { useEffect } from 'react'
import { Link, Navigate, Outlet, useLocation, useParams } from 'react-router-dom'
import { useBrands } from '../brands/useBrands'
import { brandsPickerPath } from '../lib/brandPath'

function RequireBrand() {
  const { brandId = '' } = useParams<{ brandId: string }>()
  const location = useLocation()
  const { brands, loading, loadFailed, selectedBrand, selectBrand } = useBrands()

  const allowed = brands.find((brand) => brand.external_id === brandId) ?? null

  useEffect(() => {
    if (allowed == null) return
    if (selectedBrand?.id === allowed.external_id && selectedBrand.name === allowed.name) {
      return
    }
    selectBrand({ id: allowed.external_id, name: allowed.name })
  }, [allowed, selectedBrand, selectBrand])

  if (loading) {
    return (
      <div className="app-loading">
        <p>Loading…</p>
      </div>
    )
  }

  if (loadFailed) {
    return (
      <div className="app-loading">
        <p>We couldn&apos;t load your brands right now. Please try again in a moment.</p>
        <p>
          <Link to="/brands">Choose a brand</Link>
        </p>
      </div>
    )
  }

  if (allowed == null) {
    return (
      <Navigate to={brandsPickerPath(`${location.pathname}${location.search}`)} replace />
    )
  }

  if (selectedBrand?.id !== allowed.external_id) {
    return (
      <div className="app-loading">
        <p>Loading…</p>
      </div>
    )
  }

  return <Outlet />
}

export default RequireBrand
