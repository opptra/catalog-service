from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.user_service.application import Application


def get_by_name(session: Session, name: str) -> Application | None:
    return session.scalar(select(Application).where(Application.name == name))


def get_by_external_id(session: Session, external_id: UUID) -> Application | None:
    return session.scalar(select(Application).where(Application.external_id == external_id))
