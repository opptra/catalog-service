import { useEffect, useState } from 'react'

interface PipelineProgressBarProps {
  startedAt: string
  /** Job updated_at — used for finished duration when the job is terminal. */
  updatedAt: string
  jobStatus: string
  completedCount: number
  totalCount: number
  /** True while a status poll request is in flight. */
  isFetching?: boolean
}

function formatStartedAt(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000))
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60

  if (hours > 0) {
    return `${hours}h ${minutes}m ${seconds}s`
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds}s`
  }
  return `${seconds}s`
}

function PipelineProgressBar({
  startedAt,
  updatedAt,
  jobStatus,
  completedCount,
  totalCount,
  isFetching = false,
}: PipelineProgressBarProps) {
  const jobFinished = jobStatus === 'COMPLETED' || jobStatus === 'FAILED'
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (jobFinished) return
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [jobFinished])

  const startedMs = new Date(startedAt).getTime()
  const updatedMs = new Date(updatedAt).getTime()
  const safeTotal = Math.max(totalCount, 0)
  const safeCompleted = Math.min(Math.max(completedCount, 0), safeTotal)
  const percent = safeTotal === 0 ? 0 : Math.round((safeCompleted / safeTotal) * 100)
  const done = jobFinished || (safeTotal > 0 && safeCompleted >= safeTotal)

  // Completed jobs: finished duration is updated_at − created_at (started_at).
  const elapsedMs =
    jobFinished && !Number.isNaN(startedMs) && !Number.isNaN(updatedMs)
      ? Math.max(0, updatedMs - startedMs)
      : Number.isNaN(startedMs)
        ? 0
        : now - startedMs

  return (
    <div
      className={`pipeline-progress${done ? ' pipeline-progress--done' : ' pipeline-progress--live'}${isFetching ? ' pipeline-progress--fetching' : ''}`}
      role="status"
      aria-live="polite"
    >
      <div className="pipeline-progress__meta">
        <p className="pipeline-progress__timing">
          Pipeline started <strong>{formatStartedAt(startedAt)}</strong>
          <span className="pipeline-progress__sep">·</span>
          <span>
            {jobFinished ? 'Finished in' : 'Running for'}{' '}
            <strong>{formatElapsed(elapsedMs)}</strong>
          </span>
        </p>
        <div className="pipeline-progress__right">
          <p className="pipeline-progress__sync" aria-hidden={!isFetching && done}>
            <span
              className={`pipeline-progress__sync-dot${isFetching ? ' pipeline-progress__sync-dot--active' : ''}`}
            />
            <span className="pipeline-progress__sync-label">
              {done
                ? isFetching
                  ? 'Refreshing…'
                  : 'Up to date'
                : isFetching
                  ? 'Checking progress…'
                  : 'Live updates'}
            </span>
          </p>
          <p className="pipeline-progress__count">
            <strong>
              {safeCompleted} / {safeTotal}
            </strong>{' '}
            SKUs complete
          </p>
        </div>
      </div>
      <div
        className="pipeline-progress__track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={safeTotal}
        aria-valuenow={safeCompleted}
        aria-label="SKU generation progress"
      >
        <div
          className={`pipeline-progress__fill${done ? ' pipeline-progress__fill--done' : ''}`}
          style={{ width: `${Math.max(percent, done ? 100 : percent === 0 ? 4 : percent)}%` }}
        />
        {!done ? <div className="pipeline-progress__pulse" aria-hidden="true" /> : null}
      </div>
    </div>
  )
}

export default PipelineProgressBar
