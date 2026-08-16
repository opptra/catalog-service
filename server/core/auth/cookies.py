"""Set and clear the catalog session cookie (httpOnly JWT)."""

from fastapi import Request, Response

from core.config import settings
from services import session_jwt

SESSION_COOKIE_NAME = "catalog_session"
SESSION_COOKIE_PATH = "/api"


def cookie_should_be_secure(request: Request) -> bool:
    """Prefer explicit ``COOKIE_SECURE``; otherwise follow the request scheme."""
    if settings.cookie_secure is not None:
        return settings.cookie_secure
    return request.url.scheme == "https"


def set_session_cookie(response: Response, token: str, *, secure: bool) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=session_jwt.session_max_age_seconds(),
        path=SESSION_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=secure,
    )


def clear_session_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path=SESSION_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=secure,
    )
