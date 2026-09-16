/** Pick the batch-preview SKU index from `?sku=` or 1-based `?n=`. Unknown values fall back to the first row. */

export function parseSkuPositionParam(nParam: string | null): number | null {
  if (nParam == null || nParam.length === 0) {
    return null
  }
  if (!/^[1-9]\d*$/.test(nParam)) {
    return null
  }
  return Number(nParam)
}

export function resolveSkuSelection(
  skuJobs: readonly { sku_id: string }[],
  skuParam: string | null,
  nParam: string | null = null,
): number {
  if (skuJobs.length === 0) {
    return 0
  }
  if (skuParam != null && skuParam.length > 0) {
    const index = skuJobs.findIndex((job) => job.sku_id === skuParam)
    if (index >= 0) {
      return index
    }
  }
  const position = parseSkuPositionParam(nParam)
  if (position != null && position <= skuJobs.length) {
    return position - 1
  }
  return 0
}
