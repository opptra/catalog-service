import secrets
from typing import Protocol

from google.auth.exceptions import GoogleAuthError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from core.auth.policy import AuthPolicy
from core.config import settings
from core.exceptions import UserNotFoundError
from services import users as user_service

_CLIENT_ID_HEADER = "client-id"
_CLIENT_TOKEN_HEADER = "client-token"


class AuthError(Exception):
    """Raised by an ``Authenticator`` on failure. Carries the HTTP status to return."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class Authenticator(Protocol):
    async def authenticate(self, request: Request) -> None:
        """Verify the request, raising ``AuthError`` on failure.

        On success, binds whatever state the route needs onto ``request.state``.
        """
        ...


class GoogleUserAuthenticator:
    """Verifies ``Authorization: Bearer <google-id-token>`` and binds the user."""

    async def authenticate(self, request: Request) -> None:
        token = _extract_bearer_token(request)
        if token is None:
            raise AuthError(401, "Missing bearer token")

        google_client = request.app.state.google_auth
        try:
            claims = await run_in_threadpool(google_client.verify_id_token, token)
        except (ValueError, GoogleAuthError) as exc:
            raise AuthError(401, "Invalid Google ID token") from exc

        try:
            user = await run_in_threadpool(_lookup_user, request, claims["sub"])
        except UserNotFoundError as exc:
            raise AuthError(401, str(exc)) from exc

        request.state.user = user


class InternalClientAuthenticator:
    """Verifies ``client-id`` + ``client-token`` headers against ``settings.service_clients``."""

    async def authenticate(self, request: Request) -> None:
        client_id = (request.headers.get(_CLIENT_ID_HEADER) or "").strip()
        client_token = (request.headers.get(_CLIENT_TOKEN_HEADER) or "").strip()
        if not client_id or not client_token:
            raise AuthError(401, "Missing client-id or client-token")

        expected = settings.service_clients.get(client_id)
        if expected is None or not secrets.compare_digest(client_token, expected):
            raise AuthError(401, "Invalid client credentials")

        request.state.service_client_id = client_id


class NoAuthAuthenticator:
    async def authenticate(self, request: Request) -> None:
        return None


AUTHENTICATORS: dict[AuthPolicy, Authenticator] = {
    AuthPolicy.GOOGLE_USER: GoogleUserAuthenticator(),
    AuthPolicy.INTERNAL_CLIENT: InternalClientAuthenticator(),
    AuthPolicy.PUBLIC: NoAuthAuthenticator(),
}


def _extract_bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization")
    if not header:
        return None
    scheme, _, credentials = header.partition(" ")
    if scheme.lower() != "bearer" or not credentials.strip():
        return None
    return credentials.strip()


def _lookup_user(request: Request, google_sub: str):
    session = request.app.state.user_db.session_factory()
    try:
        return user_service.get_user_by_google_sub(session, google_sub)
    finally:
        session.close()
