import { useBrandsStore } from './brandsStore'

export function useBrands() {
  const brands = useBrandsStore((state) => state.brands)
  const loading = useBrandsStore((state) => state.loading)
  const loadFailed = useBrandsStore((state) => state.loadFailed)
  const selectedBrand = useBrandsStore((state) => state.selectedBrand)
  const selectBrand = useBrandsStore((state) => state.selectBrand)
  const clearSelection = useBrandsStore((state) => state.clearSelection)
  const refetch = useBrandsStore((state) => state.refetch)

  return {
    brands,
    loading,
    loadFailed,
    selectedBrand,
    selectBrand,
    clearSelection,
    refetch,
  }
}
