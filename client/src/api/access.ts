import api from './axios'

export interface AccessibleBrand {
  external_id: string
  name: string
  granted_at: string
}

export interface BrandUser {
  external_id: string
  name: string
  email: string
  granted_at: string
  has_signed_in: boolean
}

export interface InviteBrandUserResponse extends BrandUser {
  created: boolean
}

export async function listAccessibleBrands(): Promise<AccessibleBrand[]> {
  const { data } = await api.get<AccessibleBrand[]>('/access/brands')
  return data
}

export async function listBrandUsers(brandExternalId: string): Promise<BrandUser[]> {
  const { data } = await api.get<BrandUser[]>(`/access/brands/${brandExternalId}/users`)
  return data
}

export async function inviteBrandUser(
  brandExternalId: string,
  email: string,
): Promise<InviteBrandUserResponse> {
  const { data } = await api.post<InviteBrandUserResponse>('/access/brands/users/invite', {
    brand_external_id: brandExternalId,
    email,
  })
  return data
}
