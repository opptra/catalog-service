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

export interface JobExpectedAttribute {
  attribute_external_id: string
  name: string
  data_type: 'TEXT' | 'IMAGE' | string
  quantity: number
  group_label: string | null
}

export interface JobSkuGenerationStatusItem {
  external_id: string
  sku_id: string
  display_name: string | null
  status: string
  tasks: Record<string, string>
}

export interface JobStatusResponse {
  external_id: string
  status: string
  started_at: string
  updated_at: string
  marketplace_external_id: string | null
  marketplace_name: string | null
  category_external_id: string | null
  category_name: string | null
  sku_count: number
  completed_sku_count: number
  failed_sku_count: number
  pending_sku_count: number
  expected_attributes: JobExpectedAttribute[]
  sku_generation_jobs: JobSkuGenerationStatusItem[]
}

export interface JobListItem {
  external_id: string
  status: string
  started_at: string
  updated_at: string
  marketplace_name: string | null
  category_name: string | null
  sku_count: number
  completed_sku_count: number
  failed_sku_count: number
  pending_sku_count: number
}

export interface JobListResponse {
  items: JobListItem[]
}

const listJobsInflight = new Map<string, Promise<JobListResponse>>()

export interface SkuGenerationJobAttributeSlot {
  attribute_external_id: string
  name: string
  data_type: 'TEXT' | 'IMAGE' | string
  slot: number
  quantity: number
  task_status: string
  value_external_id: string | null
  version: number | null
  value: string | null
  value_is_signed_url: boolean
}

export interface SkuGenerationJobContentResponse {
  external_id: string
  job_external_id: string
  sku_id: string
  display_name: string | null
  status: string
  tasks: Record<string, string>
  marketplace_external_id: string | null
  marketplace_name: string | null
  attributes: SkuGenerationJobAttributeSlot[]
}

export async function listJobs(brandExternalId: string): Promise<JobListResponse> {
  const existing = listJobsInflight.get(brandExternalId)
  if (existing) {
    return existing
  }

  const request = api
    .get<JobListResponse>('/jobs', {
      params: { brand_external_id: brandExternalId },
    })
    .then(({ data }) => data)
    .finally(() => {
      if (listJobsInflight.get(brandExternalId) === request) {
        listJobsInflight.delete(brandExternalId)
      }
    })

  listJobsInflight.set(brandExternalId, request)
  return request
}

export async function createJob(body: CreateJobRequest): Promise<CreateJobResponse> {
  const { data } = await api.post<CreateJobResponse>('/jobs', body)
  return data
}

export async function completeJob(externalId: string): Promise<CompleteJobResponse> {
  const { data } = await api.post<CompleteJobResponse>(`/jobs/${externalId}/complete`)
  return data
}

export async function getJobStatus(jobExternalId: string): Promise<JobStatusResponse> {
  const { data } = await api.get<JobStatusResponse>(`/jobs/${jobExternalId}/status`)
  return data
}

export async function getSkuGenerationJobContent(
  skuGenerationJobExternalId: string,
): Promise<SkuGenerationJobContentResponse> {
  const { data } = await api.get<SkuGenerationJobContentResponse>(
    `/jobs/sku/${skuGenerationJobExternalId}`,
  )
  return data
}
