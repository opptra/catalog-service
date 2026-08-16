from fastapi import HTTPException, Response
from google.auth.exceptions import GoogleAuthError
from starlette.requests import Request

from core.auth import SecureAPIRouter, no_auth
from core.auth.cookies import (
    clear_session_cookie,
    cookie_should_be_secure,
    set_session_cookie,
)
from core.deps import GoogleAuthClientDep, UserSessionDep
from core.exceptions import InvalidGoogleClaimsError
from dto.request.auth import GoogleLoginRequest
from dto.response.users import UserResponse
from services import session_jwt
from services import users as user_service

router = SecureAPIRouter(prefix="/auth", tags=["auth"])


@router.post("/google", response_model=UserResponse)
@no_auth
def google_login(
    payload: GoogleLoginRequest,
    session: UserSessionDep,
    google_client: GoogleAuthClientDep,
    request: Request,
    response: Response,
) -> UserResponse:
    try:
        claims = google_client.verify_id_token(payload.id_token)
        user = user_service.upsert_google_user(session, claims)
    except (ValueError, GoogleAuthError) as exc:
        raise HTTPException(status_code=401, detail="Invalid Google ID token") from exc
    except InvalidGoogleClaimsError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    token = session_jwt.encode(user_external_id=user.external_id)
    set_session_cookie(response, token, secure=cookie_should_be_secure(request))
    return UserResponse.model_validate(user)


@router.post("/logout", status_code=204)
@no_auth
def logout(request: Request, response: Response) -> None:
    """Clear the session cookie. Public so an expired cookie can still log out."""
    clear_session_cookie(response, secure=cookie_should_be_secure(request))
