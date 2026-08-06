from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.catalog.attribute_enums import AttributeName
from entities.catalog.attribute_master import AttributeMaster


def get_by_id(session: Session, attribute_id: int) -> AttributeMaster | None:
    return session.get(AttributeMaster, attribute_id)


def list_by_ids(session: Session, attribute_ids: Sequence[int]) -> Sequence[AttributeMaster]:
    if not attribute_ids:
        return []
    return session.scalars(
        select(AttributeMaster).where(AttributeMaster.id.in_(attribute_ids))
    ).all()


def get_by_external_id(session: Session, external_id: UUID) -> AttributeMaster | None:
    return session.scalar(select(AttributeMaster).where(AttributeMaster.external_id == external_id))


def list_by_external_ids(
    session: Session, external_ids: Sequence[UUID]
) -> Sequence[AttributeMaster]:
    if not external_ids:
        return []
    return session.scalars(
        select(AttributeMaster).where(AttributeMaster.external_id.in_(list(external_ids)))
    ).all()


def get_by_name(session: Session, name: AttributeName) -> AttributeMaster | None:
    return session.scalar(select(AttributeMaster).where(AttributeMaster.name == name))


def list_all(session: Session) -> Sequence[AttributeMaster]:
    return session.scalars(select(AttributeMaster).order_by(AttributeMaster.id.asc())).all()
