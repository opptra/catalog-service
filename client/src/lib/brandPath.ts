/** App paths that carry workspace brand as `/b/:brandId/…`. */

export function brandPath(brandId: string, rest: string): string {
  const suffix = rest.startsWith('/') ? rest : `/${rest}`
  return `/b/${brandId}${suffix}`
}

export function isSafeInternalPath(path: string): boolean {
  return (
    path.startsWith('/') &&
    !path.startsWith('//') &&
    !path.startsWith('/\\') &&
    !path.includes('://') &&
    !path.includes('\\')
  )
}

export function readNextParam(searchParams: URLSearchParams): string | null {
  const next = searchParams.get('next')
  if (next == null || next.length === 0 || !isSafeInternalPath(next)) {
    return null
  }
  return next
}

export function loginPath(next: string | null): string {
  if (next == null || next === '/login' || next.startsWith('/login?')) {
    return '/login'
  }
  if (!isSafeInternalPath(next)) {
    return '/login'
  }
  const params = new URLSearchParams()
  params.set('next', next)
  return `/login?${params.toString()}`
}

export function brandsPickerPath(next?: string | null): string {
  if (next == null || next.length === 0 || !isSafeInternalPath(next)) {
    return '/brands'
  }
  const params = new URLSearchParams()
  params.set('next', next)
  return `/brands?${params.toString()}`
}

/** After picking a brand, return to `next` only if it belongs to that brand. */
export function pathAfterBrandSelect(brandId: string, next: string | null): string {
  if (next != null && nextBelongsToBrand(next, brandId)) {
    return next
  }
  return brandPath(brandId, '/workspace')
}

function nextBelongsToBrand(next: string, brandId: string): boolean {
  if (!isSafeInternalPath(next)) {
    return false
  }
  const prefix = `/b/${brandId}`
  return next === prefix || next.startsWith(`${prefix}/`) || next.startsWith(`${prefix}?`)
}
