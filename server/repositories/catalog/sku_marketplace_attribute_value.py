from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.catalog.sku_marketplace_attribute_value import SkuMarketplaceAttributeValue


def get_by_id(session: Session, value_id: int) -> SkuMarketplaceAttributeValue | None:
    return session.get(SkuMarketplaceAttributeValue, value_id)


def get_latest_by_external_id(
    session: Session, external_id: UUID
) -> SkuMarketplaceAttributeValue | None:
    """external_id is shared across versions — return the highest version row."""
    return session.scalar(
        select(SkuMarketplaceAttributeValue)
        .where(SkuMarketplaceAttributeValue.external_id == external_id)
        .order_by(SkuMarketplaceAttributeValue.version.desc())
        .limit(1)
    )
