import api from './axios'

export interface MarketplaceSelectionMarketplace {
  external_id: string
  name: string
}

export interface MarketplaceSelectionAttributeItem {
  external_id: string
  allows_quantity: boolean
}

export interface MarketplaceSelectionAttribute {
  id: string
  label: string
  items: MarketplaceSelectionAttributeItem[]
}

export interface MarketplaceSelection {
  marketplaces: MarketplaceSelectionMarketplace[]
  attributes: MarketplaceSelectionAttribute[]
}

export async function getMarketplaceSelection(): Promise<MarketplaceSelection> {
  const { data } = await api.get<MarketplaceSelection>('/catalog/marketplace-selection')
  return data
}
