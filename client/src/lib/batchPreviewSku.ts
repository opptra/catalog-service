/** Pick the batch-preview SKU index from `?sku=`. Unknown or missing ids fall back to the first row. */
export function resolveSkuSelection(
  skuJobs: readonly { sku_id: string }[],
  skuParam: string | null,
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
  return 0
}
