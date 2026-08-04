from uuid import UUID

from fastapi import HTTPException

from core.auth import SecureAPIRouter
from core.deps import CatalogSessionDep, CurrentUserDep, UserSessionDep
from dto.response.brand_access import BrandAccessResponse
from dto.response.users import UserResponse
from services import brand_access as brand_access_service

router = SecureAPIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
def get_current_user(user: CurrentUserDep) -> UserResponse:
    return UserResponse.model_validate(user)


@router.get("/{external_id}/brands", response_model=list[BrandAccessResponse])
def get_user_brand_access(
    external_id: UUID,
    user: CurrentUserDep,
    user_session: UserSessionDep,
    catalog_session: CatalogSessionDep,
) -> list[BrandAccessResponse]:
    if external_id != user.external_id:
        raise HTTPException(status_code=403, detail="Cannot access another user's brand access")

    return brand_access_service.list_brand_access_for_user(user_session, catalog_session, user.id)
