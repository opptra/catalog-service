import { create } from 'zustand'
import { listAccessibleBrands, type AccessibleBrand } from '../api/access'
import type { User } from '../api/auth'
import { useAuthStore } from '../auth/authStore'
import {
  clearSelectedBrand as clearStoredBrand,
  getSelectedBrand,
  setSelectedBrand as persistSelectedBrand,
  type Brand,
} from '../data/brands'

interface BrandsState {
  brands: AccessibleBrand[]
  loading: boolean
  loadFailed: boolean
  selectedBrand: Brand | null
  selectBrand: (brand: Brand) => void
  clearSelection: () => void
  refetch: () => void
  loadForUser: (user: User | null) => Promise<void>
}

let brandsRequestId = 0

export const useBrandsStore = create<BrandsState>((set, get) => ({
  brands: [],
  loading: false,
  loadFailed: false,
  selectedBrand: getSelectedBrand(),

  selectBrand: (brand: Brand) => {
    persistSelectedBrand(brand)
    set({ selectedBrand: brand })
  },

  clearSelection: () => {
    clearStoredBrand()
    set({ selectedBrand: null })
  },

  refetch: () => {
    void get().loadForUser(useAuthStore.getState().user)
  },

  loadForUser: async (user: User | null) => {
    if (!user) {
      brandsRequestId += 1
      clearStoredBrand()
      set({
        brands: [],
        loading: false,
        loadFailed: false,
        selectedBrand: null,
      })
      return
    }

    const requestId = ++brandsRequestId
    set({ loading: true, loadFailed: false })

    try {
      const data = await listAccessibleBrands()
      if (requestId !== brandsRequestId) return

      const current = getSelectedBrand()
      if (!current) {
        set({ brands: data, loading: false, loadFailed: false, selectedBrand: null })
        return
      }

      const stillAllowed = data.some((brand) => brand.external_id === current.id)
      if (stillAllowed) {
        set({ brands: data, loading: false, loadFailed: false, selectedBrand: current })
      } else {
        clearStoredBrand()
        set({ brands: data, loading: false, loadFailed: false, selectedBrand: null })
      }
    } catch {
      if (requestId !== brandsRequestId) return
      set({ brands: [], loading: false, loadFailed: true })
    }
  },
}))

let boundToAuth = false

/** Load/clear brands whenever the authenticated user changes. */
export function bindBrandsToAuth(): void {
  if (boundToAuth) return
  boundToAuth = true

  let previousExternalId: string | null | undefined

  useAuthStore.subscribe((state) => {
    const nextExternalId = state.user?.external_id ?? null
    if (nextExternalId === previousExternalId) return
    previousExternalId = nextExternalId
    void useBrandsStore.getState().loadForUser(state.user)
  })
}
