from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from core.exceptions import InvalidGoogleClaimsError, UserNotFoundError
from entities.user_service.user import User
from repositories.user_service import user as user_repository


def get_user_by_external_id(session: Session, external_id: UUID) -> User:
    user = user_repository.get_by_external_id(session, external_id)
    if user is None:
        raise UserNotFoundError(str(external_id))
    return user


def upsert_google_user(session: Session, claims: dict[str, Any]) -> User:
    if not claims.get("email_verified"):
        raise InvalidGoogleClaimsError("Google email is not verified")

    google_sub: str = claims["sub"]
    email: str = claims["email"]
    name: str = claims.get("name", email)

    user = user_repository.get_by_google_sub(session, google_sub)
    if user is None:
        user = user_repository.get_by_email(session, email.strip().lower())
        if user is not None:
            user.google_sub = google_sub
            if name:
                user.name = name
            user = user_repository.save(session, user)
        else:
            user = user_repository.create(
                session,
                name=name,
                email=email.strip().lower(),
                google_sub=google_sub,
            )

    return user


def get_user_by_google_sub(session: Session, google_sub: str) -> User:
    user = user_repository.get_by_google_sub(session, google_sub)
    if user is None:
        raise UserNotFoundError(google_sub)
    return user
