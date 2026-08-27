import api from './axios'

export interface FlatfileImageFile {
  sku_id: string
  filename: string
  content_type: string
}

export interface CreateFlatfileJobRequest {
  category_external_id: string
  template_filename: string
  template_content_type: string
  images: FlatfileImageFile[]
}

export interface SignedObjectUrl {
  object_key: string
  upload_url?: string | null
  delete_url?: string | null
  content_type?: string | null
  sku_id?: string | null
  filename?: string | null
}

export interface CreateFlatfileJobResponse {
  external_id: string
  status: string
  template: SignedObjectUrl
  images: SignedObjectUrl[]
  deletes: SignedObjectUrl[]
}

export interface CompleteFlatfileJobResponse {
  external_id: string
  status: string
  sku_ids: string[]
}

export async function createFlatfileJob(
  body: CreateFlatfileJobRequest,
): Promise<CreateFlatfileJobResponse> {
  const { data } = await api.post<CreateFlatfileJobResponse>('/jobs/flatfile', body)
  return data
}

export async function completeFlatfileJob(
  externalId: string,
): Promise<CompleteFlatfileJobResponse> {
  const { data } = await api.post<CompleteFlatfileJobResponse>(
    `/jobs/flatfile/${externalId}/complete`,
  )
  return data
}

export function guessTemplateContentType(filename: string): string {
  const lower = filename.toLowerCase()
  if (lower.endsWith('.csv')) return 'text/csv'
  if (lower.endsWith('.xls')) return 'application/vnd.ms-excel'
  return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
}

/** Direct PUT to a GCS signed URL (not the catalog API). */
export async function putToSignedUrl(
  url: string,
  body: Blob | File,
  contentType: string,
): Promise<void> {
  const response = await fetch(url, {
    method: 'PUT',
    headers: { 'Content-Type': contentType },
    body,
  })
  if (!response.ok) {
    throw new Error(`Upload failed (${response.status})`)
  }
}

/** Direct DELETE via a GCS signed URL (not the catalog API). */
export async function deleteWithSignedUrl(url: string): Promise<void> {
  const response = await fetch(url, { method: 'DELETE' })
  if (!response.ok && response.status !== 404) {
    throw new Error(`Delete failed (${response.status})`)
  }
}
