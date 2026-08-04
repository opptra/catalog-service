import api from './axios'

export interface CreateJobAttribute {
  attribute_id: number
  quantity?: number
}

export interface CreateJobRequest {
  sku_ids: number[]
  marketplace_id: number
  attributes: CreateJobAttribute[]
}

export interface CreatedSkuJob {
  sku_id: number
  external_id: string
}

export interface CreateJobResponse {
  external_id: string
  status: string
  marketplace_id: number
  sku_ids: number[]
  sku_jobs: CreatedSkuJob[]
  attribute_ids: number[]
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
