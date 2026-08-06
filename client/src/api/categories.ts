import api from './axios'

export interface CategoryPathNode {
  external_id: string
  name: string
}

export interface LeafCategory {
  external_id: string
  name: string
  path: CategoryPathNode[]
}

export interface LeafCategoryPage {
  items: LeafCategory[]
  offset: number
  limit: number
  has_more: boolean
}

export interface CategoryTemplateField {
  name: string
  mandatory: boolean
}

export interface CategoryTemplate {
  external_id: string
  name: string
  fields: CategoryTemplateField[]
}

export const LEAF_CATEGORY_PAGE_SIZE = 10

export async function listLeafCategories(offset = 0): Promise<LeafCategoryPage> {
  const { data } = await api.get<LeafCategoryPage>('/catalog/categories/leaves', {
    params: { offset, limit: LEAF_CATEGORY_PAGE_SIZE },
  })
  return data
}

export async function getCategoryTemplate(externalId: string): Promise<CategoryTemplate> {
  const { data } = await api.get<CategoryTemplate>(
    `/catalog/categories/${externalId}/template`,
  )
  return data
}
