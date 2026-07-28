from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.user import User


def get_by_id(session: Session, user_id: int) -> User | None:
    return session.get(User, user_id)


def get_by_external_id(session: Session, external_id: UUID) -> User | None:
    return session.scalar(select(User).where(User.external_id == external_id))
