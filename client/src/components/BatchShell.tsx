import type { ReactNode } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useBrands } from '../brands/useBrands'
import AppHeader from './AppHeader'
import BatchStepper from './BatchStepper'

interface BatchShellProps {
  title: string
  stepIndex: number
  stepLabel: string
  children: ReactNode
  bodyClassName?: string
}

function BatchShell({ title, stepIndex, stepLabel, children, bodyClassName }: BatchShellProps) {
  const navigate = useNavigate()
  const { selectedBrand: brand } = useBrands()

  if (!brand) {
    return <Navigate to="/brands" replace />
  }

  return (
    <div className="page-shell">
      <AppHeader
        brandName={brand.name}
        showExecutionHistory
        onExecutionHistoryClick={() => navigate('/workspace/batch/summer-tees')}
      />
      <main className="batch-page">
        <div className="batch-page__top">
          <div className="batch-page__title-row">
            <h1 className="batch-page__title">{title}</h1>
            <p className="batch-page__step-count">{stepLabel}</p>
          </div>
          <BatchStepper activeIndex={stepIndex} />
        </div>
        <div className={bodyClassName ?? 'batch-page__body batch-page__body--wide'}>{children}</div>
      </main>
    </div>
  )
}

export default BatchShell
