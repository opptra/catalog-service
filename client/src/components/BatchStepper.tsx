import { BATCH_STEPS } from '../data/batchDraft'

interface BatchStepperProps {
  activeIndex: number
}

function BatchStepper({ activeIndex }: BatchStepperProps) {
  return (
    <ol className="batch-stepper" aria-label="Batch steps">
      {BATCH_STEPS.map((step, index) => {
        const isActive = index === activeIndex
        const isComplete = index < activeIndex
        return (
          <li
            key={step}
            className={`batch-stepper__item${isActive ? ' batch-stepper__item--active' : ''}${isComplete ? ' batch-stepper__item--complete' : ''}`}
          >
            <span className="batch-stepper__dot" aria-hidden="true" />
            <span className="batch-stepper__label">{step}</span>
            {index < BATCH_STEPS.length - 1 ? (
              <span className="batch-stepper__line" aria-hidden="true" />
            ) : null}
          </li>
        )
      })}
    </ol>
  )
}

export default BatchStepper
