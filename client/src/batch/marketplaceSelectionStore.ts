import { create } from 'zustand'
import {
  getMarketplaceSelection,
  type MarketplaceSelectionAttribute,
  type MarketplaceSelectionMarketplace,
} from '../api/catalog'

export type MarketplaceSelectionStatus = 'idle' | 'loading' | 'ready' | 'error'

interface MarketplaceSelectionState {
  status: MarketplaceSelectionStatus
  marketplaces: MarketplaceSelectionMarketplace[]
  attributes: MarketplaceSelectionAttribute[]
  /** Load once; concurrent callers share the same in-flight request. */
  ensureLoaded: () => Promise<void>
  /** Force a new fetch (e.g. retry after error). */
  reload: () => Promise<void>
  clear: () => void
}

let inFlight: Promise<void> | null = null

async function loadSelection(
  set: (partial: Partial<MarketplaceSelectionState>) => void,
  get: () => MarketplaceSelectionState,
  force: boolean,
): Promise<void> {
  if (!force && get().status === 'ready') return
  if (inFlight) return inFlight

  set({ status: 'loading' })

  inFlight = (async () => {
    try {
      const data = await getMarketplaceSelection()
      set({
        status: 'ready',
        marketplaces: data.marketplaces,
        attributes: data.attributes,
      })
    } catch {
      set({
        status: 'error',
        marketplaces: [],
        attributes: [],
      })
    } finally {
      inFlight = null
    }
  })()

  return inFlight
}

export const useMarketplaceSelectionStore = create<MarketplaceSelectionState>((set, get) => ({
  status: 'idle',
  marketplaces: [],
  attributes: [],

  ensureLoaded: () => loadSelection(set, get, false),

  reload: () => loadSelection(set, get, true),

  clear: () => {
    inFlight = null
    set({
      status: 'idle',
      marketplaces: [],
      attributes: [],
    })
  },
}))
