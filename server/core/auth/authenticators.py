import secrets
from typing import Protocol
from uuid import UUID

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from core.auth.cookies import SESSION_COOKIE_NAME
from core.auth.policy import AuthPolicy
from core.config import settings
from core.exceptions import UserNotFoundError
from services import session_jwt
from services import users as user_service
from services.session_jwt import SessionJwtError

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


class SessionAuthenticator:
    """Verifies the ``catalog_session`` httpOnly JWT and binds the user."""

    async def authenticate(self, request: Request) -> None:
        cookie_token = (request.cookies.get(SESSION_COOKIE_NAME) or "").strip()
        if not cookie_token:
            if settings.dev_mode:
                await _bind_dev_user(request)
                return
            raise AuthError(401, "Missing session cookie")

        try:
            claims = session_jwt.decode(cookie_token)
        except SessionJwtError as exc:
            if settings.dev_mode:
                await _bind_dev_user(request)
                return
            raise AuthError(401, "Invalid session token") from exc

        sub = claims.get("sub")
        if not sub or not isinstance(sub, str):
            if settings.dev_mode:
                await _bind_dev_user(request)
                return
            raise AuthError(401, "Invalid session token")

        try:
            user_external_id = UUID(sub)
        except ValueError as exc:
            if settings.dev_mode:
                await _bind_dev_user(request)
                return
            raise AuthError(401, "Invalid session token") from exc

        try:
            user = await run_in_threadpool(_lookup_user_by_external_id, request, user_external_id)
        except UserNotFoundError as exc:
            if settings.dev_mode:
                await _bind_dev_user(request)
                return
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
    AuthPolicy.GOOGLE_USER: SessionAuthenticator(),
    AuthPolicy.INTERNAL_CLIENT: InternalClientAuthenticator(),
    AuthPolicy.PUBLIC: NoAuthAuthenticator(),
}


def _lookup_user_by_external_id(request: Request, external_id: UUID):
    session = request.app.state.user_db.session_factory()
    try:
        return user_service.get_user_by_external_id(session, external_id)
    finally:
        session.close()


def _lookup_dev_user(request: Request):
    session = request.app.state.user_db.session_factory()
    try:
        return user_service.get_dev_user(session, settings.dev_user_email)
    finally:
        session.close()


async def _bind_dev_user(request: Request) -> None:
    try:
        user = await run_in_threadpool(_lookup_dev_user, request)
    except UserNotFoundError as exc:
        raise AuthError(401, str(exc)) from exc
    request.state.user = user
