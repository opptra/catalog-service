import api from './axios'

export interface CreateJobAttribute {
  attribute_external_id: string
  quantity?: number
}

export interface CreateJobRequest {
  sku_ids: string[]
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
  brand_external_id: string | null
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
  brand_external_id: string | null
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
  prompt: string | null
}

export interface RegenerateAttributeValueRequest {
  improvement: string
}

export interface RestoreAttributeValueRequest {
  version: number
}

export interface RegenerateAttributeValueResponse {
  value_external_id: string
  attribute_external_id: string
  name: string
  data_type: 'TEXT' | 'IMAGE' | string
  slot: number
  version: number
  value: string
  value_is_signed_url: boolean
  prompt: string | null
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
  // brandExternalId is only used for in-flight dedupe; Brand-Id is set by axios.
  const existing = listJobsInflight.get(brandExternalId)
  if (existing) {
    return existing
  }

  const request = api
    .get<JobListResponse>('/jobs')
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

export interface JobContentExportColumn {
  key: string
  label: string
  data_type: string
}

export interface JobContentExportResponse {
  job_external_id: string
  marketplace_external_id: string | null
  marketplace_name: string | null
  columns: JobContentExportColumn[]
  rows: Array<Record<string, string | null>>
}

export async function getJobContentExport(
  jobExternalId: string,
): Promise<JobContentExportResponse> {
  const { data } = await api.get<JobContentExportResponse>(
    `/jobs/${jobExternalId}/content-export`,
  )
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

/** Re-run only the PENDING/FAILED tasks of one SKU generation job. */
export async function retrySkuGenerationJob(
  skuGenerationJobExternalId: string,
): Promise<void> {
  await api.post(`/jobs/sku/${skuGenerationJobExternalId}/retry`)
}

export async function regenerateAttributeValue(
  valueExternalId: string,
  body: RegenerateAttributeValueRequest,
): Promise<RegenerateAttributeValueResponse> {
  const { data } = await api.post<RegenerateAttributeValueResponse>(
    `/jobs/attribute-values/${valueExternalId}/regenerate`,
    body,
  )
  return data
}

export async function restoreAttributeValue(
  valueExternalId: string,
  body: RestoreAttributeValueRequest,
): Promise<RegenerateAttributeValueResponse> {
  const { data } = await api.post<RegenerateAttributeValueResponse>(
    `/jobs/attribute-values/${valueExternalId}/restore`,
    body,
  )
  return data
}
