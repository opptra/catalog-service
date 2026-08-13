import api from './axios'

export interface ListingFillGap {
  sku_id: string
  column_label: string
  reason: string
}

export interface FillListingResponse {
  job_external_id: string
  filled_file_url: string
  gaps: ListingFillGap[]
}

export async function fillListing(jobExternalId: string): Promise<FillListingResponse> {
  const { data } = await api.post<FillListingResponse>('/listings/fill', {
    job_external_id: jobExternalId,
  })
  return data
}
