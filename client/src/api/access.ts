import api from './axios'

export interface AccessibleBrand {
  external_id: string
  name: string
  granted_at: string
}

export async function listAccessibleBrands(): Promise<AccessibleBrand[]> {
  const { data } = await api.get<AccessibleBrand[]>('/access/brands')
  return data
}
