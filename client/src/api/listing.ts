import api from './axios'

export interface ListingFillGap {
  sku_id: string
  column_label: string
  reason: string
  message: string
}

export interface StartListingFillResponse {
  status: string
  job_external_id: string
  sku_count: number
  estimated_minutes: number
  message: string
}

export interface JobGroupListingFileItem {
  marketplace_external_id: string
  marketplace_name: string
  job_external_id: string
  filename: string | null
  filled_file_url: string | null
  generated_at: string | null
  gaps: ListingFillGap[]
}

export interface JobGroupListingFilesResponse {
  job_group_id: string
  files: JobGroupListingFileItem[]
}

export interface FillListingRequest {
  job_group_id: string
  marketplace_external_id: string
}

export async function fillListing(body: FillListingRequest): Promise<StartListingFillResponse> {
  const { data } = await api.post<StartListingFillResponse>('/listings/fill', body)
  return data
}

export async function getJobGroupListingFiles(
  jobGroupId: string,
): Promise<JobGroupListingFilesResponse> {
  const { data } = await api.get<JobGroupListingFilesResponse>(
    `/job-groups/${jobGroupId}/listing-files`,
  )
  return data
}
