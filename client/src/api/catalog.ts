import api from './axios'
import type { MarketplaceAttributeConfig } from './jobs'

export interface MarketplaceSelectionAttributeItem {
  external_id: string
  name: string
  allows_quantity: boolean
  quantity: number
  config: MarketplaceAttributeConfig
}

export interface MarketplaceSelectionAttribute {
  id: string
  label: string
  items: MarketplaceSelectionAttributeItem[]
}

export interface MarketplaceSelectionMarketplace {
  external_id: string
  name: string
  attributes: MarketplaceSelectionAttribute[]
}

export interface MarketplaceSelection {
  marketplaces: MarketplaceSelectionMarketplace[]
}

export async function getMarketplaceSelection(): Promise<MarketplaceSelection> {
  const { data } = await api.get<MarketplaceSelection>('/catalog/marketplace-selection')
  return data
}
