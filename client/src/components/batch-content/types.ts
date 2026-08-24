import type { ImageVerification } from '../../api/jobs'

export interface ContentImage {
  id: string
  url: string | null
  label: string
  valueExternalId?: string | null
  version?: number | null
  verification?: ImageVerification | null
}
