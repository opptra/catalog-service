"""Access grants for the current user (brands and future resource types)."""

from core.auth import SecureAPIRouter
from core.deps import CatalogSessionDep, CurrentUserDep, UserSessionDep
from dto.response.access import AccessibleBrandResponse
from services import access as access_service

router = SecureAPIRouter(prefix="/access", tags=["access"])


@router.get("/brands", response_model=list[AccessibleBrandResponse])
def list_accessible_brands(
    user: CurrentUserDep,
    user_session: UserSessionDep,
    catalog_session: CatalogSessionDep,
) -> list[AccessibleBrandResponse]:
    return access_service.list_accessible_brands(user_session, catalog_session, user.id)
