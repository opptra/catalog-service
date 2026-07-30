from fastapi import APIRouter, HTTPException
from google.auth.exceptions import GoogleAuthError

from core.deps import GoogleAuthClientDep, UserSessionDep
from core.exceptions import InvalidGoogleClaimsError
from dto.auth import GoogleLoginRequest
from dto.users import UserResponse
from services import users as user_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/google", response_model=UserResponse)
def google_login(
    payload: GoogleLoginRequest,
    session: UserSessionDep,
    google_client: GoogleAuthClientDep,
) -> UserResponse:
    try:
        claims = google_client.verify_id_token(payload.id_token)
        user = user_service.upsert_google_user(session, claims)
    except (ValueError, GoogleAuthError) as exc:
        raise HTTPException(status_code=401, detail="Invalid Google ID token") from exc
    except InvalidGoogleClaimsError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    return UserResponse.model_validate(user)
