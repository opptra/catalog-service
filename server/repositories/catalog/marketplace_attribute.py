from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.catalog.marketplace_attribute import MarketplaceAttribute


def list_by_marketplace_id(session: Session, marketplace_id: int) -> Sequence[MarketplaceAttribute]:
    return session.scalars(
        select(MarketplaceAttribute)
        .where(MarketplaceAttribute.marketplace_id == marketplace_id)
        .order_by(MarketplaceAttribute.id.asc())
    ).all()


def list_by_marketplace_ids(
    session: Session, marketplace_ids: Sequence[int]
) -> Sequence[MarketplaceAttribute]:
    if not marketplace_ids:
        return []
    return session.scalars(
        select(MarketplaceAttribute)
        .where(MarketplaceAttribute.marketplace_id.in_(list(marketplace_ids)))
        .order_by(MarketplaceAttribute.marketplace_id.asc(), MarketplaceAttribute.id.asc())
    ).all()


def get_by_marketplace_and_attribute(
    session: Session,
    marketplace_id: int,
    attribute_id: int,
) -> MarketplaceAttribute | None:
    return session.scalar(
        select(MarketplaceAttribute).where(
            MarketplaceAttribute.marketplace_id == marketplace_id,
            MarketplaceAttribute.attribute_id == attribute_id,
        )
    )
