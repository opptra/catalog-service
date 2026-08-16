from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.user_service.role import Role


def get_by_name(session: Session, name: str) -> Role | None:
    return session.scalar(select(Role).where(Role.name == name))
