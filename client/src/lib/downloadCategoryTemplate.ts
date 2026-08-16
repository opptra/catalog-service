import type { CategoryTemplate } from '../api/categories'

const MANDATORY_FILL = 'FECACA'
const MANDATORY_FONT = '991B1B'
const OPTIONAL_FILL = 'BBF7D0'
const OPTIONAL_FONT = '166534'

function slugify(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
}

/** Build a styled .xlsx template in the browser and trigger an immediate download. */
export async function downloadCategoryTemplate(template: CategoryTemplate): Promise<void> {
  const { Workbook } = await import('exceljs')
  const workbook = new Workbook()
  workbook.creator = 'Listing Studio'
  const sheet = workbook.addWorksheet('Template', {
    views: [{ state: 'frozen', ySplit: 2 }],
  })

  if (template.fields.length === 0) {
    sheet.getCell('A1').value = 'No fields configured for this subcategory yet.'
    sheet.getColumn(1).width = 48
  } else {
    // Mandatory columns first (stable within each group) so the sheet is easier to fill.
    const orderedFields = [
      ...template.fields.filter((field) => field.mandatory),
      ...template.fields.filter((field) => !field.mandatory),
    ]

    orderedFields.forEach((field, index) => {
      const column = index + 1
      const header = sheet.getCell(1, column)
      const legend = sheet.getCell(2, column)
      const fill = field.mandatory ? MANDATORY_FILL : OPTIONAL_FILL
      const font = field.mandatory ? MANDATORY_FONT : OPTIONAL_FONT

      header.value = field.name
      header.font = { bold: true, color: { argb: `FF${font}` } }
      header.fill = {
        type: 'pattern',
        pattern: 'solid',
        fgColor: { argb: `FF${fill}` },
      }
      header.alignment = { vertical: 'middle', horizontal: 'center', wrapText: true }

      legend.value = field.mandatory ? 'Mandatory' : 'Optional'
      legend.font = { size: 10, color: { argb: `FF${font}` } }
      legend.fill = {
        type: 'pattern',
        pattern: 'solid',
        fgColor: { argb: `FF${fill}` },
      }
      legend.alignment = { vertical: 'middle', horizontal: 'center' }

      sheet.getColumn(column).width = Math.max(14, field.name.length + 4)
    })

    sheet.getRow(1).height = 22
    sheet.getRow(2).height = 18
  }

  const buffer = await workbook.xlsx.writeBuffer()
  const blob = new Blob([buffer], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${slugify(template.name) || 'category'}-template.xlsx`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
