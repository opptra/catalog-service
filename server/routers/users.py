from core.auth import SecureAPIRouter
from core.deps import CurrentUserDep
from dto.response.users import UserResponse

router = SecureAPIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
def get_current_user(user: CurrentUserDep) -> UserResponse:
    return UserResponse.model_validate(user)
