from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.catalog.attribute_master import AttributeMaster


def get_by_id(session: Session, attribute_id: int) -> AttributeMaster | None:
    return session.get(AttributeMaster, attribute_id)


def get_by_external_id(session: Session, external_id: UUID) -> AttributeMaster | None:
    return session.scalar(
        select(AttributeMaster).where(AttributeMaster.external_id == external_id)
    )
