import api from './axios'

export interface CreateJobAttribute {
  attribute_external_id: string
  quantity?: number
}

export interface CreateJobRequest {
  sku_ids: string[]
  brand_external_id: string
  marketplace_external_id: string
  attributes: CreateJobAttribute[]
}

export interface CreatedSkuGenerationJob {
  sku_id: string
  external_id: string
}

export interface CreateJobResponse {
  external_id: string
  status: string
  marketplace_external_id: string
  sku_ids: string[]
  sku_generation_jobs: CreatedSkuGenerationJob[]
  attribute_external_ids: string[]
  workflow_execution: string | null
}

export interface CompleteJobResponse {
  external_id: string
  status: string
}

export async function createJob(body: CreateJobRequest): Promise<CreateJobResponse> {
  const { data } = await api.post<CreateJobResponse>('/jobs', body)
  return data
}

export async function completeJob(externalId: string): Promise<CompleteJobResponse> {
  const { data } = await api.post<CompleteJobResponse>(`/jobs/${externalId}/complete`)
  return data
}
