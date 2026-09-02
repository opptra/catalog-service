import type { SkuAttributeItem } from '../api/jobs'

function csvEscape(value: string): string {
  if (/[",\n\r]/.test(value)) {
    return `"${value.replaceAll('"', '""')}"`
  }
  return value
}

function safeFilename(value: string): string {
  const trimmed = value.trim().replace(/[/\\?%*:|"<>]/g, '_')
  return trimmed || 'sku'
}

/** Filled attributes only (header + one row). Built on click, not on modal open. */
export function downloadSkuAttributesCsv(skuId: string, fields: SkuAttributeItem[]): void {
  const filled = fields.filter((field) => field.value.trim().length > 0)
  if (filled.length === 0) {
    throw new Error('No attributes to export.')
  }

  const header = filled.map((field) => csvEscape(field.name)).join(',')
  const row = filled.map((field) => csvEscape(field.value)).join(',')
  const blob = new Blob([`\uFEFF${header}\n${row}\n`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${safeFilename(skuId)}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
