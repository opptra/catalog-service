from fastapi import APIRouter

from core.deps import CurrentUserDep
from dto.users import UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
def get_current_user(user: CurrentUserDep) -> UserResponse:
    return UserResponse.model_validate(user)
