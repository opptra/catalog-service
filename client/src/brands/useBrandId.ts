import { useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { brandPath } from '../lib/brandPath'

/** Catalog brand `external_id` from `/b/:brandId/…`. Only use under RequireBrand. */
export function useBrandId(): string {
  const { brandId } = useParams<{ brandId: string }>()
  if (brandId == null || brandId.length === 0) {
    throw new Error('useBrandId must be used on a /b/:brandId route')
  }
  return brandId
}

export function useBrandHref(): (rest: string) => string {
  const brandId = useBrandId()
  return useCallback((rest: string) => brandPath(brandId, rest), [brandId])
}
