export interface Brand {
  id: string
  name: string
  categories: string
  lastBatchLabel: string
}

export const BRANDS: Brand[] = [
  {
    id: 'nike',
    name: 'Nike',
    categories: 'Running Shoes, Apparel',
    lastBatchLabel: 'last batch · 2h ago',
  },
  {
    id: 'adidas',
    name: 'Adidas',
    categories: 'Apparel, Footwear',
    lastBatchLabel: 'last batch · 3d ago',
  },
]

const SELECTED_BRAND_KEY = 'listingStudio.selectedBrandId'

export function getSelectedBrandId(): string | null {
  return sessionStorage.getItem(SELECTED_BRAND_KEY)
}

export function setSelectedBrandId(brandId: string): void {
  sessionStorage.setItem(SELECTED_BRAND_KEY, brandId)
}

export function clearSelectedBrandId(): void {
  sessionStorage.removeItem(SELECTED_BRAND_KEY)
}

export function getBrandById(brandId: string): Brand | undefined {
  return BRANDS.find((brand) => brand.id === brandId)
}
