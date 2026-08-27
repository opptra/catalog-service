import api from './axios'

export interface MarketplaceAttributeConfig {
  text?: {
    chars?: { min?: number; max?: number }
    items?: {
      count?: number
      min?: number
      max?: number
      chars?: { min?: number; max?: number }
    }
  }
  image?: {
    quantity?: number
    aspect_ratio?: string
  }
}

export interface CreateJobAttribute {
  attribute_external_id: string
  quantity?: number
}

export interface CreateJobMarketplace {
  marketplace_external_id: string
  attributes: CreateJobAttribute[]
}

export interface CreateJobRequest {
  sku_ids: string[]
  marketplaces: CreateJobMarketplace[]
}

export interface CreatedSkuGenerationJob {
  sku_id: string
  external_id: string
}

export interface CreateJobChildResponse {
  external_id: string
  job_group_id: string
  status: string
  marketplace_external_id: string
  marketplace_name: string | null
  sku_ids: string[]
  sku_generation_jobs: CreatedSkuGenerationJob[]
  attribute_external_ids: string[]
  workflow_execution: string | null
}

export interface CreateJobResponse {
  job_group_id: string
  jobs: CreateJobChildResponse[]
  sku_ids: string[]
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
  config?: MarketplaceAttributeConfig | null
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
  job_group_id: string | null
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

export interface JobGroupMarketplaceStatus {
  job_external_id: string
  marketplace_external_id: string
  marketplace_name: string
  status: string
}

export interface JobGroupStatusResponse {
  job_group_id: string
  status: string
  started_at: string
  updated_at: string
  brand_external_id: string | null
  created_by_name: string | null
  sku_count: number
  completed_sku_count: number
  failed_sku_count: number
  pending_sku_count: number
  marketplaces: JobGroupMarketplaceStatus[]
  active_job: JobStatusResponse | null
}

export interface JobListMarketplaceItem {
  external_id: string
  name: string
  status: string
}

export interface JobListItem {
  job_group_id: string
  external_id: string
  status: string
  started_at: string
  updated_at: string
  brand_external_id: string | null
  marketplace_name: string | null
  marketplaces: JobListMarketplaceItem[]
  category_name: string | null
  created_by_name: string | null
  execution_number: number
  sku_count: number
  completed_sku_count: number
  failed_sku_count: number
  pending_sku_count: number
}

export interface JobListResponse {
  items: JobListItem[]
  next_offset: number | null
  has_more: boolean
}

const listJobsInflight = new Map<string, Promise<JobListResponse>>()

export interface ImageVerificationMismatch {
  kind: string
  source_field: string | null
  catalog: string | null
  observed: string | null
}

export interface ImageVerificationAxes {
  identity?: number | null
  claims?: number | null
  quality?: number | null
}

export interface ImageVerificationSlotContext {
  name?: string | null
  role?: string | null
  kind?: string | null
}

export interface ImageVerificationSnapshot {
  v: number
  status: string
  model: string
  attempt: number
  confidence?: number | null
  threshold?: number | null
  reasoning?: string | null
  observed_text?: string[] | null
  mismatches?: ImageVerificationMismatch[] | null
  axes?: ImageVerificationAxes | null
  slot?: ImageVerificationSlotContext | null
  error?: string | null
}

export interface ImageVerification extends ImageVerificationSnapshot {
  previous?: ImageVerificationSnapshot | null
}

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
  verification: ImageVerification | null
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
  verification: ImageVerification | null
}

export interface SkuGenerationJobContentResponse {
  external_id: string
  job_external_id: string
  job_group_id: string | null
  sku_id: string
  display_name: string | null
  status: string
  tasks: Record<string, string>
  marketplace_external_id: string | null
  marketplace_name: string | null
  attributes: SkuGenerationJobAttributeSlot[]
}

export async function listJobs(
  brandExternalId: string,
  options: { offset?: number; limit?: number } = {},
): Promise<JobListResponse> {
  const offset = options.offset ?? 0
  const limit = options.limit ?? 50
  const cacheKey = `${brandExternalId}:${offset}:${limit}`
  const existing = listJobsInflight.get(cacheKey)
  if (existing) {
    return existing
  }

  const request = api
    .get<JobListResponse>('/jobs', { params: { offset, limit } })
    .then(({ data }) => data)
    .finally(() => {
      if (listJobsInflight.get(cacheKey) === request) {
        listJobsInflight.delete(cacheKey)
      }
    })

  listJobsInflight.set(cacheKey, request)
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

export async function getJobGroupStatus(
  jobGroupId: string,
  marketplaceExternalId?: string,
): Promise<JobGroupStatusResponse> {
  const { data } = await api.get<JobGroupStatusResponse>(`/job-groups/${jobGroupId}/status`, {
    params: marketplaceExternalId
      ? { marketplace_external_id: marketplaceExternalId }
      : undefined,
  })
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

export interface SkuProductImage {
  filename: string
  url: string
}

export interface SkuProductImagesResponse {
  sku_id: string
  images: SkuProductImage[]
}

export async function getSkuProductImages(
  skuGenerationJobExternalId: string,
): Promise<SkuProductImagesResponse> {
  const { data } = await api.get<SkuProductImagesResponse>(
    `/jobs/sku/${skuGenerationJobExternalId}/product-images`,
  )
  return data
}

export interface SkuAttributeItem {
  name: string
  value: string
}

export interface SkuAttributesResponse {
  sku_id: string
  attributes: SkuAttributeItem[]
}

export async function getSkuAttributes(
  skuGenerationJobExternalId: string,
): Promise<SkuAttributesResponse> {
  const { data } = await api.get<SkuAttributesResponse>(
    `/jobs/sku/${skuGenerationJobExternalId}/attributes`,
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

export interface SkuImageDownloadItem {
  marketplace: string
  folder: string
  filename: string
  url: string
}

export interface SkuImageDownloadResponse {
  sku_id: string
  filename: string
  images: SkuImageDownloadItem[]
}

/** Signed URLs for one SKU across every marketplace — client downloads bytes and builds the zip. */
export async function getSkuImageDownload(
  jobGroupId: string,
  skuId: string,
): Promise<SkuImageDownloadResponse> {
  const { data } = await api.get<SkuImageDownloadResponse>(
    `/job-groups/${jobGroupId}/skus/${skuId}/images`,
  )
  return data
}
