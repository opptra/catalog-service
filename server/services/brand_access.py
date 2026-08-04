from sqlalchemy.orm import Session

from dto.response.brand_access import BrandAccessResponse
from repositories.catalog import brand as catalog_brand_repository
from repositories.user_service import user_access_grant as grant_repository


def list_brand_access_for_user(
    user_session: Session,
    catalog_session: Session,
    user_id: int,
) -> list[BrandAccessResponse]:
    grants = grant_repository.list_brand_access_for_user(user_session, user_id)
    if not grants:
        return []

    catalog_brands = catalog_brand_repository.list_by_user_service_brand_ids(
        catalog_session, [grant.external_id for grant in grants]
    )
    catalog_brand_by_user_service_id = {
        brand.user_service_brand_id: brand for brand in catalog_brands
    }

    result = []
    for grant in grants:
        catalog_brand = catalog_brand_by_user_service_id.get(grant.external_id)
        if catalog_brand is None:
            continue
        result.append(
            BrandAccessResponse(
                external_id=catalog_brand.external_id,
                name=catalog_brand.name,
                granted_at=grant.granted_at,
            )
        )
    return result
