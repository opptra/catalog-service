import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import chevronRight from '../assets/chevron-right.svg'
import { useBrands } from '../brands/useBrands'
import AppHeader from '../components/AppHeader'
import { STATIC_LAST_BATCH_LABEL } from '../data/brands'

function BrandSelect() {
  const navigate = useNavigate()
  const { brands, loading, loadFailed, selectBrand } = useBrands()

  useEffect(() => {
    document.title = 'Listing Studio · Select a brand'
  }, [])

  function handleSelect(brandId: string, brandName: string) {
    selectBrand({ id: brandId, name: brandName })
    navigate('/workspace')
  }

  const hasNoAccess = !loading && !loadFailed && brands.length === 0

  return (
    <div className="page-shell">
      <AppHeader />
      <main className="brand-page">
        <div className="brand-page__content">
          <h1 className="brand-page__title">Select a brand</h1>
          <p className="brand-page__subtitle">
            Each brand is a separate workspace. Data, batches and generated content never cross
            between them.
          </p>

          {loading ? <p className="brand-page__status">Loading your brands…</p> : null}

          {loadFailed ? (
            <p className="brand-page__status">
              We couldn&apos;t load your brands right now. Please try again in a moment.
            </p>
          ) : null}

          {hasNoAccess ? (
            <p className="brand-page__status">
              You don&apos;t have access to any brands yet. Contact your admin to get access to the
              brands you need.
            </p>
          ) : null}

          {!loading && !loadFailed && brands.length > 0 ? (
            <div className="brand-grid">
              {brands.map((brand) => (
                <button
                  key={brand.external_id}
                  type="button"
                  className="brand-card"
                  onClick={() => handleSelect(brand.external_id, brand.name)}
                >
                  <div className="brand-card__header">
                    <span className="brand-card__name">{brand.name}</span>
                    <img src={chevronRight} alt="" className="brand-card__chevron" />
                  </div>
                  <span className="brand-card__meta">{STATIC_LAST_BATCH_LABEL}</span>
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </main>
    </div>
  )
}

export default BrandSelect
