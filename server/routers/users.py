from uuid import UUID

from fastapi import APIRouter, HTTPException

from core.deps import CurrentUserDep, UserSessionDep
from dto.brand_access import BrandAccessResponse
from dto.users import UserResponse
from services import brand_access as brand_access_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
def get_current_user(user: CurrentUserDep) -> UserResponse:
    return UserResponse.model_validate(user)


@router.get("/{external_id}/brands", response_model=list[BrandAccessResponse])
def get_user_brand_access(
    external_id: UUID,
    user: CurrentUserDep,
    session: UserSessionDep,
) -> list[BrandAccessResponse]:
    if external_id != user.external_id:
        raise HTTPException(status_code=403, detail="Cannot access another user's brand access")

    rows = brand_access_service.list_brand_access_for_user(session, user.id)
    return [BrandAccessResponse.model_validate(row) for row in rows]
