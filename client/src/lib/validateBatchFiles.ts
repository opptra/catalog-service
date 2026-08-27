import type { CategoryTemplateField } from '../api/categories'
import {
  collectZipTopLevels,
  IMAGE_EXT,
  isIgnoredZipName,
  resolveZipRootPrefix,
} from './batchZip'
import { needsSrgbJpegConvert, storedImageTarget } from './ensureSrgbImage'

export type ValidationStepId =
  | 'read_product'
  | 'mandatory_columns'
  | 'read_images'
  | 'sku_mapping'
  | 'summary'

export type ValidationStepStatus = 'pending' | 'running' | 'passed' | 'failed'

export interface ValidationStep {
  id: ValidationStepId
  label: string
  status: ValidationStepStatus
  detail?: string
}

export interface ValidationIssue {
  group: 'CSV' | 'CSV ↔ ZIP MAPPING' | 'FILES'
  key: string
  message: string
  ok: boolean
}

export interface SkuImageManifestEntry {
  sku_id: string
  filenames: string[]
}

export interface BatchValidationResult {
  skuCount: number
  validCount: number
  problemCount: number
  imageCount: number
  passed: boolean
  issues: ValidationIssue[]
  problemSkus: string[]
  successItems: string[]
  steps: ValidationStep[]
  skuImages: SkuImageManifestEntry[]
}

export type ValidationProgressHandler = (steps: ValidationStep[]) => void

const SKU_HEADER = 'SKU'

const STEP_DEFS: Array<{ id: ValidationStepId; label: string }> = [
  { id: 'read_product', label: 'Reading product file' },
  { id: 'mandatory_columns', label: 'Checking mandatory columns in the flat file' },
  {
    id: 'read_images',
    label: 'Reading images ZIP and SKU folders',
  },
  {
    id: 'sku_mapping',
    label: 'Matching every SKU to a folder with at least one image',
  },
  { id: 'summary', label: 'Summarizing overall status' },
]

function initialSteps(): ValidationStep[] {
  return STEP_DEFS.map((step) => ({ ...step, status: 'pending' as const }))
}

function setStep(
  steps: ValidationStep[],
  id: ValidationStepId,
  status: ValidationStepStatus,
  detail?: string,
): ValidationStep[] {
  return steps.map((step) =>
    step.id === id ? { ...step, status, detail: detail ?? step.detail } : step,
  )
}

function cellText(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean') return String(value).trim()
  if (typeof value === 'object' && 'text' in value && typeof value.text === 'string') {
    return value.text.trim()
  }
  if (typeof value === 'object' && 'result' in value) {
    return cellText(value.result)
  }
  return String(value).trim()
}

function parseCsv(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let cell = ''
  let inQuotes = false

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i]
    const next = text[i + 1]

    if (inQuotes) {
      if (char === '"' && next === '"') {
        cell += '"'
        i += 1
      } else if (char === '"') {
        inQuotes = false
      } else {
        cell += char
      }
      continue
    }

    if (char === '"') {
      inQuotes = true
    } else if (char === ',') {
      row.push(cell)
      cell = ''
    } else if (char === '\n') {
      row.push(cell)
      rows.push(row)
      row = []
      cell = ''
    } else if (char !== '\r') {
      cell += char
    }
  }

  if (cell.length > 0 || row.length > 0) {
    row.push(cell)
    rows.push(row)
  }

  return rows.filter((r) => r.some((c) => c.trim().length > 0))
}

function isLegendRow(values: string[]): boolean {
  const nonEmpty = values.filter((v) => v.trim().length > 0)
  if (nonEmpty.length === 0) return false
  return nonEmpty.every((v) => {
    const lower = v.trim().toLowerCase()
    return lower === 'mandatory' || lower === 'optional'
  })
}

interface ProductTable {
  headers: string[]
  rows: string[][]
}

async function readProductTable(file: File): Promise<ProductTable> {
  const name = file.name.toLowerCase()

  if (name.endsWith('.csv')) {
    const text = await file.text()
    const grid = parseCsv(text)
    if (grid.length === 0) {
      throw new Error('Product file is empty.')
    }
    const headers = grid[0].map((h) => h.trim())
    let dataStart = 1
    if (grid.length > 1 && isLegendRow(grid[1])) dataStart = 2
    return {
      headers,
      rows: grid.slice(dataStart).map((r) => headers.map((_, i) => (r[i] ?? '').trim())),
    }
  }

  if (name.endsWith('.xlsx') || name.endsWith('.xls')) {
    const { Workbook } = await import('exceljs')
    const workbook = new Workbook()
    const buffer = await file.arrayBuffer()
    await workbook.xlsx.load(buffer)
    const sheet = workbook.worksheets[0]
    if (!sheet) {
      throw new Error('Product spreadsheet has no sheets.')
    }

    const grid: string[][] = []
    sheet.eachRow({ includeEmpty: false }, (row) => {
      const values: string[] = []
      row.eachCell({ includeEmpty: true }, (cell, colNumber) => {
        values[colNumber - 1] = cellText(cell.value)
      })
      if (values.some((v) => v.length > 0)) {
        grid.push(values.map((v) => v ?? ''))
      }
    })

    if (grid.length === 0) {
      throw new Error('Product spreadsheet is empty.')
    }

    const headers = grid[0].map((h) => h.trim())
    let dataStart = 1
    if (grid.length > 1 && isLegendRow(grid[1])) dataStart = 2
    return {
      headers,
      rows: grid.slice(dataStart).map((r) => headers.map((_, i) => (r[i] ?? '').trim())),
    }
  }

  throw new Error('Unsupported product file type. Use CSV, XLS, or XLSX.')
}

interface FolderImages {
  imageCount: number
  files: string[]
  cmykCount: number
  collisions: string[]
  claimedStored: Map<string, string>
}

/**
 * Expected ZIP shape:
 *   <batch-root>/
 *     <SKU>/             ← folder name matches the SKU column value exactly
 *       image.jpg
 *
 * Fallback: multiple top-level folders → each is a SKU folder (no batch wrapper).
 */
async function readZipFolders(file: File): Promise<Map<string, FolderImages>> {
  const JSZip = (await import('jszip')).default
  const zip = await JSZip.loadAsync(await file.arrayBuffer())

  const zipPaths = Object.entries(zip.files).map(([path, entry]) => ({
    path,
    dir: entry.dir,
  }))

  const topLevels = collectZipTopLevels(zipPaths)
  const rootPrefix = resolveZipRootPrefix(topLevels)

  const folders = new Map<string, FolderImages>()

  function ensureFolder(name: string): FolderImages {
    const existing = folders.get(name)
    if (existing) return existing
    const created = {
      imageCount: 0,
      files: [] as string[],
      cmykCount: 0,
      collisions: [] as string[],
      claimedStored: new Map<string, string>(),
    }
    folders.set(name, created)
    return created
  }

  for (const { path, dir } of zipPaths) {
    const parts = path.replace(/\\/g, '/').split('/').filter(Boolean)
    if (parts.length === 0 || isIgnoredZipName(parts[0])) continue
    if (rootPrefix && parts[0] !== rootPrefix) continue

    const relative = rootPrefix ? parts.slice(1) : parts
    if (relative.length === 0 || isIgnoredZipName(relative[0])) continue

    const skuId = relative[0]
    // Directory entry for the SKU folder itself (may have no files yet).
    if (dir && relative.length === 1) {
      ensureFolder(skuId)
      continue
    }

    // File or nested path under the SKU folder: root/<SKU>/...
    if (relative.length < 2) continue

    const fileName = relative[relative.length - 1]
    if (fileName.startsWith('.') || isIgnoredZipName(fileName)) continue

    const current = ensureFolder(skuId)
    if (!dir && IMAGE_EXT.test(fileName)) {
      current.imageCount += 1
      current.files.push(fileName)
      const zipEntry = zip.files[path]
      if (zipEntry) {
        const bytes = await zipEntry.async('uint8array')
        if (needsSrgbJpegConvert(bytes)) current.cmykCount += 1
        const stored = storedImageTarget(fileName, bytes).storedFilename
        const prior = current.claimedStored.get(stored)
        if (prior !== undefined) {
          current.collisions.push(
            `“${prior}” and “${fileName}” would both upload as ${stored}`,
          )
        } else {
          current.claimedStored.set(stored, fileName)
        }
      }
    }
  }

  return folders
}

function findHeaderIndex(headers: string[], name: string): number {
  return headers.findIndex((h) => h === name)
}

function tick(): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, 180)
  })
}

export async function validateBatchFiles(options: {
  productFile: File
  imagesFile: File
  mandatoryFields: CategoryTemplateField[]
  onProgress?: ValidationProgressHandler
}): Promise<BatchValidationResult> {
  const { productFile, imagesFile, mandatoryFields, onProgress } = options
  let steps = initialSteps()
  const issues: ValidationIssue[] = []

  const report = (next: ValidationStep[]) => {
    steps = next
    onProgress?.(steps)
  }

  report(setStep(steps, 'read_product', 'running'))
  await tick()

  let table: ProductTable
  try {
    table = await readProductTable(productFile)
    report(setStep(steps, 'read_product', 'passed', `${table.rows.length} data rows`))
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Could not read product file.'
    issues.push({ group: 'FILES', key: 'product file', message, ok: false })
    report(setStep(steps, 'read_product', 'failed', message))
    return finalize(0, 0, 0, 0, issues, [], steps, [])
  }

  const skuIndex = findHeaderIndex(table.headers, SKU_HEADER)
  if (skuIndex < 0) {
    issues.push({
      group: 'FILES',
      key: 'CSV columns',
      message: 'SKU column is missing',
      ok: false,
    })
  } else {
    issues.push({
      group: 'FILES',
      key: 'CSV columns',
      message: 'SKU column present',
      ok: true,
    })
  }

  report(setStep(steps, 'mandatory_columns', 'running'))
  await tick()

  const requiredNames = [
    SKU_HEADER,
    ...mandatoryFields.filter((f) => f.mandatory).map((f) => f.name),
  ]
  const uniqueRequired = [...new Set(requiredNames.map((n) => n.trim()).filter(Boolean))]
  const missingColumns: string[] = []

  for (const name of uniqueRequired) {
    if (findHeaderIndex(table.headers, name) < 0) {
      missingColumns.push(name)
      issues.push({
        group: 'CSV',
        key: 'columns',
        message: `missing mandatory column “${name}”`,
        ok: false,
      })
    }
  }

  if (missingColumns.length === 0) {
    issues.push({
      group: 'FILES',
      key: 'mandatory columns',
      message:
        uniqueRequired.length > 1
          ? `all ${uniqueRequired.length} mandatory columns present`
          : 'SKU column present',
      ok: true,
    })
    report(setStep(steps, 'mandatory_columns', 'passed'))
  } else {
    report(
      setStep(
        steps,
        'mandatory_columns',
        'failed',
        `${missingColumns.length} missing: ${missingColumns.join(', ')}`,
      ),
    )
  }

  report(setStep(steps, 'read_images', 'running', 'Reading ZIP and checking JPEG color space'))
  await tick()

  let folders: Map<string, FolderImages>
  try {
    folders = await readZipFolders(imagesFile)
    const folderCount = folders.size
    const imageCount = [...folders.values()].reduce((sum, f) => sum + f.imageCount, 0)
    report(
      setStep(steps, 'read_images', 'passed', `${folderCount} folders · ${imageCount} images`),
    )
    issues.push({
      group: 'FILES',
      key: 'zip structure',
      message: 'readable',
      ok: true,
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Could not read images ZIP.'
    issues.push({ group: 'FILES', key: 'zip structure', message, ok: false })
    report(setStep(steps, 'read_images', 'failed', message))
    return finalize(table.rows.length, 0, table.rows.length, 0, issues, [], steps, [])
  }

  report(setStep(steps, 'sku_mapping', 'running'))
  await tick()

  const skuCounts = new Map<string, number>()
  const rowProblems = new Set<number>()
  let imageCount = 0

  table.rows.forEach((row, index) => {
    const rowNumber = index + 1
    const sku = skuIndex >= 0 ? row[skuIndex] ?? '' : ''

    if (!sku) {
      issues.push({
        group: 'CSV',
        key: `row ${rowNumber}`,
        message: 'SKU is empty',
        ok: false,
      })
      rowProblems.add(index)
      return
    }

    skuCounts.set(sku, (skuCounts.get(sku) ?? 0) + 1)

    for (const field of mandatoryFields) {
      if (!field.mandatory) continue
      if (field.name === SKU_HEADER) continue
      const col = findHeaderIndex(table.headers, field.name)
      if (col < 0) {
        // Column absent from the file — this SKU cannot satisfy the requirement.
        rowProblems.add(index)
        continue
      }
      if (!(row[col] ?? '').trim()) {
        issues.push({
          group: 'CSV',
          key: `row ${rowNumber}`,
          message: `“${field.name}” is required and blank`,
          ok: false,
        })
        rowProblems.add(index)
      }
    }
  })

  for (const [sku, count] of skuCounts) {
    if (count > 1) {
      issues.push({
        group: 'CSV',
        key: `SKU`,
        message: `duplicate SKU “${sku}”`,
        ok: false,
      })
      table.rows.forEach((row, index) => {
        if ((row[skuIndex] ?? '') === sku) rowProblems.add(index)
      })
    }
  }

  const matchedFolders = new Set<string>()

  table.rows.forEach((row, index) => {
    const sku = skuIndex >= 0 ? row[skuIndex] ?? '' : ''
    if (!sku) return

    const folder = folders.get(sku)
    if (!folder) {
      issues.push({
        group: 'CSV ↔ ZIP MAPPING',
        key: sku,
        message: `no folder named /${sku}/ in the zip`,
        ok: false,
      })
      rowProblems.add(index)
      return
    }

    matchedFolders.add(sku)
    if (folder.collisions.length > 0) {
      for (const message of folder.collisions) {
        issues.push({
          group: 'FILES',
          key: sku,
          message,
          ok: false,
        })
      }
      rowProblems.add(index)
      return
    }
    if (folder.imageCount === 0) {
      issues.push({
        group: 'CSV ↔ ZIP MAPPING',
        key: `/${sku}/`,
        message: 'folder exists but contains 0 images',
        ok: false,
      })
      rowProblems.add(index)
      return
    }

    imageCount += folder.imageCount
  })

  for (const [folderName] of folders) {
    if (matchedFolders.has(folderName)) continue
    issues.push({
      group: 'CSV ↔ ZIP MAPPING',
      key: `/${folderName}/`,
      message: 'folder in zip has no matching row in the CSV',
      ok: false,
    })
  }

  const problemSkus = new Set<string>()
  table.rows.forEach((row, index) => {
    if (!rowProblems.has(index)) return
    const sku = skuIndex >= 0 ? row[skuIndex] ?? '' : ''
    if (sku) problemSkus.add(sku)
    else problemSkus.add(`row ${index + 1}`)
  })
  for (const [folderName] of folders) {
    if (!matchedFolders.has(folderName)) problemSkus.add(folderName)
  }

  const skuImages: SkuImageManifestEntry[] = []
  const seenSkuIds = new Set<string>()
  table.rows.forEach((row, index) => {
    if (rowProblems.has(index)) return
    const sku = skuIndex >= 0 ? row[skuIndex] ?? '' : ''
    if (!sku || seenSkuIds.has(sku)) return
    const folder = folders.get(sku)
    if (!folder || folder.files.length === 0) return
    seenSkuIds.add(sku)
    skuImages.push({ sku_id: sku, filenames: [...folder.files] })
  })

  const skuCount = table.rows.length
  const problemCount = problemSkus.size
  const validCount = Math.max(0, skuImages.length)
  const mappingFailed = issues.some((i) => i.group === 'CSV ↔ ZIP MAPPING' && !i.ok)

  report(
    setStep(
      steps,
      'sku_mapping',
      mappingFailed || problemCount > 0 ? 'failed' : 'passed',
      `${validCount} of ${skuCount} SKUs mapped cleanly`,
    ),
  )

  report(setStep(steps, 'summary', 'running'))
  await tick()

  report(
    setStep(
      steps,
      'summary',
      skuCount > 0 && problemCount === 0 && !issues.some((issue) => !issue.ok)
        ? 'passed'
        : 'failed',
      `${skuCount} SKUs · ${validCount} valid · ${problemCount} with problems`,
    ),
  )

  return finalize(
    skuCount,
    validCount,
    problemCount,
    imageCount,
    issues,
    [...problemSkus],
    steps,
    skuImages,
    [...folders.values()].reduce((sum, folder) => sum + folder.cmykCount, 0),
  )
}

function finalize(
  skuCount: number,
  validCount: number,
  problemCount: number,
  imageCount: number,
  issues: ValidationIssue[],
  problemSkus: string[],
  steps: ValidationStep[],
  skuImages: SkuImageManifestEntry[],
  cmykCount = 0,
): BatchValidationResult {
  const passed =
    skuCount > 0 && problemCount === 0 && !issues.some((issue) => !issue.ok)

  const successItems: string[] = []
  if (passed) {
    successItems.push(
      `${skuCount} rows · all mandatory fields present`,
      `${skuCount} folders · every SKU has at least one image`,
      `${imageCount} images total`,
    )
    if (cmykCount > 0) {
      successItems.push(
        `${cmykCount} print ${cmykCount === 1 ? 'image' : 'images'} (CMYK JPEG or TIFF) will be converted to sRGB JPEG and stored as .jpg before upload`,
      )
    }
  }

  return {
    skuCount,
    validCount,
    problemCount,
    imageCount,
    passed,
    issues,
    problemSkus,
    successItems,
    steps,
    skuImages,
  }
}
