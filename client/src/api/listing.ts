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

export interface FillListingRequest {
  job_group_id: string
  marketplace_external_id: string
}

export async function fillListing(body: FillListingRequest): Promise<FillListingResponse> {
  const { data } = await api.post<FillListingResponse>('/listings/fill', body)
  return data
}
