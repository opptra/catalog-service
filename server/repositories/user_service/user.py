from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from entities.user_service.user import User
from repositories import base


def get_by_id(session: Session, user_id: int) -> User | None:
    return session.get(User, user_id)


def get_by_external_id(session: Session, external_id: UUID) -> User | None:
    return session.scalar(select(User).where(User.external_id == external_id))


def list_by_external_ids(session: Session, external_ids: Sequence[UUID]) -> Sequence[User]:
    if not external_ids:
        return []
    return session.scalars(select(User).where(User.external_id.in_(list(external_ids)))).all()


def get_by_google_sub(session: Session, google_sub: str) -> User | None:
    return session.scalar(select(User).where(User.google_sub == google_sub))


def get_by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))


def create(
    session: Session,
    *,
    name: str,
    email: str,
    google_sub: str | None = None,
) -> User:
    return base.save(session, User(name=name, email=email, google_sub=google_sub))


def save(session: Session, user: User) -> User:
    return base.save(session, user)
