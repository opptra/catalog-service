from uuid import UUID

from fastapi import APIRouter, HTTPException

from core.deps import UserSessionDep
from core.exceptions import UserNotFoundError
from dto.users import UserResponse
from services import users as user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/by-external-id/{external_id}", response_model=UserResponse)
def get_user_by_external_id(external_id: UUID, session: UserSessionDep) -> UserResponse:
    try:
        user = user_service.get_user_by_external_id(session, external_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return UserResponse.model_validate(user)
