/** Shared ZIP layout helpers for batch image archives. */

export function isIgnoredZipName(name: string): boolean {
  return name === '__MACOSX' || name.startsWith('.')
}

/**
 * Unwrap a single non-ignored top-level folder (the batch root).
 * SKU folders live directly under that root.
 */
export function resolveZipRootPrefix(topLevels: Set<string>): string | null {
  if (topLevels.size !== 1) return null
  return [...topLevels][0]
}

export function collectZipTopLevels(zipPaths: Array<{ path: string }>): Set<string> {
  const topLevels = new Set<string>()
  for (const { path } of zipPaths) {
    const parts = path.replace(/\\/g, '/').split('/').filter(Boolean)
    if (parts.length === 0 || isIgnoredZipName(parts[0])) continue
    topLevels.add(parts[0])
  }
  return topLevels
}

export const IMAGE_EXT = /\.(jpe?g|png|gif|webp|bmp|tiff?)$/i
