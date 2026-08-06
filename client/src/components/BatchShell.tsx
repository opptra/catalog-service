import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
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
  const { selectedBrand: brand } = useBrands()

  if (!brand) {
    return <Navigate to="/brands" replace />
  }

  return (
    <div className="page-shell page-shell--fixed">
      <AppHeader
        brandName={brand.name}
        showExecutionHistory
        onExecutionHistoryClick={() => {
          // Execution history / pipeline UI — not wired yet.
        }}
      />
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
