from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.user_service.user import User
from repositories import base


def get_by_id(session: Session, user_id: int) -> User | None:
    return session.get(User, user_id)


def get_by_external_id(session: Session, external_id: UUID) -> User | None:
    return session.scalar(select(User).where(User.external_id == external_id))


def get_by_google_sub(session: Session, google_sub: str) -> User | None:
    return session.scalar(select(User).where(User.google_sub == google_sub))


def get_by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == email))


def create(session: Session, *, name: str, email: str, google_sub: str) -> User:
    return base.save(session, User(name=name, email=email, google_sub=google_sub))


def save(session: Session, user: User) -> User:
    return base.save(session, user)
