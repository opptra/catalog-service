import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import chevronRight from '../assets/chevron-right.svg'
import AppHeader from '../components/AppHeader'
import { BRANDS, setSelectedBrandId, type Brand } from '../data/brands'

function BrandSelect() {
  const navigate = useNavigate()

  useEffect(() => {
    document.title = 'Listing Studio · Select a brand'
  }, [])

  function handleSelect(brand: Brand) {
    setSelectedBrandId(brand.id)
    navigate('/workspace')
  }

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
          <div className="brand-grid">
            {BRANDS.map((brand) => (
              <button
                key={brand.id}
                type="button"
                className="brand-card"
                onClick={() => handleSelect(brand)}
              >
                <div className="brand-card__header">
                  <span className="brand-card__name">{brand.name}</span>
                  <img src={chevronRight} alt="" className="brand-card__chevron" />
                </div>
                <span className="brand-card__categories">{brand.categories}</span>
                <span className="brand-card__meta">{brand.lastBatchLabel}</span>
              </button>
            ))}
          </div>
        </div>
      </main>
    </div>
  )
}

export default BrandSelect
