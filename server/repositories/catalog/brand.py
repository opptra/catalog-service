from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.catalog.brand import Brand


def get_by_id(session: Session, brand_id: int) -> Brand | None:
    return session.get(Brand, brand_id)


def get_by_external_id(session: Session, external_id: UUID) -> Brand | None:
    return session.scalar(select(Brand).where(Brand.external_id == external_id))
