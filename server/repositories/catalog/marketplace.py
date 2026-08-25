from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.catalog.marketplace import Marketplace


def get_by_id(session: Session, marketplace_id: int) -> Marketplace | None:
    return session.get(Marketplace, marketplace_id)


def get_by_external_id(session: Session, external_id: UUID) -> Marketplace | None:
    return session.scalar(select(Marketplace).where(Marketplace.external_id == external_id))


def list_all(session: Session) -> Sequence[Marketplace]:
    """Return active marketplaces only, ordered by name."""
    return session.scalars(
        select(Marketplace)
        .where(Marketplace.active.is_(True))
        .order_by(Marketplace.name.asc())
    ).all()
