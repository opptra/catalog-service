import { useEffect, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useBrands } from '../brands/useBrands'
import AppHeader from './AppHeader'
import BatchStepper from './BatchStepper'

interface BatchShellProps {
  title: string
  stepIndex: number
  stepLabel: string
  children: ReactNode
  footer?: ReactNode
  bodyClassName?: string
}

function BatchShell({
  title,
  stepIndex,
  stepLabel,
  children,
  footer,
  bodyClassName,
}: BatchShellProps) {
  const { selectedBrand: brand, loading: brandsLoading } = useBrands()
  const navigate = useNavigate()

  useEffect(() => {
    if (!brandsLoading && !brand) {
      navigate('/brands', { replace: true })
    }
  }, [brandsLoading, brand, navigate])

  // Avoid a blank screen: <Navigate> renders null while redirecting.
  if (!brand) {
    return (
      <div className="app-loading">
        <p>{brandsLoading ? 'Loading…' : 'Select a brand to continue.'}</p>
        {!brandsLoading ? (
          <p>
            <Link to="/brands">Choose a brand</Link>
          </p>
        ) : null}
      </div>
    )
  }

  return (
    <div className="page-shell page-shell--fixed">
      <AppHeader brandName={brand.name} showExecutionHistory />
      <main className="batch-page">
        <div className="batch-page__scroll">
          <div className="batch-page__top">
            <div className="batch-page__title-row">
              <h1 className="batch-page__title">{title}</h1>
              <p className="batch-page__step-count">{stepLabel}</p>
            </div>
            <BatchStepper activeIndex={stepIndex} />
          </div>
          <div className={bodyClassName ?? 'batch-page__body batch-page__body--wide'}>{children}</div>
        </div>
        {footer ? <div className="batch-page__action-bar">{footer}</div> : null}
      </main>
    </div>
  )
}

export default BatchShell
