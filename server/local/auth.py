"""Session authenticator that binds a local user when no cookie is present."""

from __future__ import annotations

import os
from uuid import UUID

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from core.auth.authenticators import AuthError
from core.auth.cookies import SESSION_COOKIE_NAME
from core.exceptions import UserNotFoundError
from entities.user_service.user import User
from repositories.user_service import user as user_repository
from services import session_jwt
from services import users as user_service
from services.session_jwt import SessionJwtError


def _local_user_email() -> str | None:
    raw = (os.environ.get("LOCAL_USER_EMAIL") or "").strip()
    return raw or None


def _lookup_user_by_external_id(request: Request, external_id: UUID):
    session = request.app.state.user_db.session_factory()
    try:
        return user_service.get_user_by_external_id(session, external_id)
    finally:
        session.close()


def _lookup_local_user(request: Request):
    session = request.app.state.user_db.session_factory()
    try:
        email = _local_user_email()
        if email:
            user = user_repository.get_by_email(session, email)
            if user is None:
                raise UserNotFoundError(email)
            return user
        user = session.scalar(select(User).order_by(User.id).limit(1))
        if user is None:
            raise UserNotFoundError("no users in local database")
        return user
    finally:
        session.close()


async def _bind_local_user(request: Request) -> None:
    try:
        user = await run_in_threadpool(_lookup_local_user, request)
    except UserNotFoundError as exc:
        raise AuthError(401, str(exc)) from exc
    request.state.user = user


class LocalSessionAuthenticator:
    """Prefer a real session cookie; otherwise bind LOCAL_USER_EMAIL or the first user."""

    async def authenticate(self, request: Request) -> None:
        cookie_token = (request.cookies.get(SESSION_COOKIE_NAME) or "").strip()
        if cookie_token:
            try:
                claims = session_jwt.decode(cookie_token)
                sub = claims.get("sub")
                if sub and isinstance(sub, str):
                    user = await run_in_threadpool(
                        _lookup_user_by_external_id, request, UUID(sub)
                    )
                    request.state.user = user
                    return
            except (SessionJwtError, UserNotFoundError, ValueError):
                pass
        await _bind_local_user(request)
