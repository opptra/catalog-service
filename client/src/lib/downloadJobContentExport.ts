import type { JobContentExportResponse } from '../api/jobs'

function slugify(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
}

/** Build an .xlsx from the content-export API payload and trigger download. */
export async function downloadJobContentExport(
  payload: JobContentExportResponse,
): Promise<void> {
  const { Workbook } = await import('exceljs')
  const workbook = new Workbook()
  workbook.creator = 'Listing Studio'
  const sheetName = payload.marketplace_name?.trim() || 'Content'
  const sheet = workbook.addWorksheet(sheetName.slice(0, 31), {
    views: [{ state: 'frozen', ySplit: 1 }],
  })

  const columns = payload.columns
  if (columns.length === 0) {
    sheet.getCell('A1').value = 'No attributes on this job.'
    sheet.getColumn(1).width = 40
  } else {
    columns.forEach((column, index) => {
      const cell = sheet.getCell(1, index + 1)
      cell.value = column.label
      cell.font = { bold: true }
      cell.alignment = { vertical: 'middle', wrapText: true }
      sheet.getColumn(index + 1).width = Math.max(14, Math.min(48, column.label.length + 4))
    })
    sheet.getRow(1).height = 22

    payload.rows.forEach((row, rowIndex) => {
      columns.forEach((column, colIndex) => {
        const raw = row[column.key]
        sheet.getCell(rowIndex + 2, colIndex + 1).value = raw ?? ''
        sheet.getCell(rowIndex + 2, colIndex + 1).alignment = {
          vertical: 'top',
          wrapText: true,
        }
      })
    })
  }

  const buffer = await workbook.xlsx.writeBuffer()
  const blob = new Blob([buffer], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  const marketSlug = slugify(payload.marketplace_name ?? 'marketplace') || 'marketplace'
  link.download = `${marketSlug}-content.xlsx`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
