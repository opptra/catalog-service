from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.catalog.sku_marketplace_attribute_value import SkuMarketplaceAttributeValue
from repositories import base


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


def get_latest_by_slot(
    session: Session,
    *,
    sku_id: int,
    marketplace_id: int,
    attribute_id: int,
    slot: int,
) -> SkuMarketplaceAttributeValue | None:
    """Latest version for a concrete (sku, marketplace, attribute, slot) identity."""
    return session.scalar(
        select(SkuMarketplaceAttributeValue)
        .where(
            SkuMarketplaceAttributeValue.sku_id == sku_id,
            SkuMarketplaceAttributeValue.marketplace_id == marketplace_id,
            SkuMarketplaceAttributeValue.attribute_id == attribute_id,
            SkuMarketplaceAttributeValue.slot == slot,
        )
        .order_by(SkuMarketplaceAttributeValue.version.desc())
        .limit(1)
    )


def list_latest_by_sku_generation_job_id(
    session: Session, sku_generation_job_id: int
) -> Sequence[SkuMarketplaceAttributeValue]:
    """Latest version per (attribute_id, slot) for one SKU generation job."""
    return session.scalars(
        select(SkuMarketplaceAttributeValue)
        .where(SkuMarketplaceAttributeValue.sku_generation_job_id == sku_generation_job_id)
        .distinct(
            SkuMarketplaceAttributeValue.attribute_id,
            SkuMarketplaceAttributeValue.slot,
        )
        .order_by(
            SkuMarketplaceAttributeValue.attribute_id.asc(),
            SkuMarketplaceAttributeValue.slot.asc(),
            SkuMarketplaceAttributeValue.version.desc(),
        )
    ).all()


def save(session: Session, row: SkuMarketplaceAttributeValue) -> SkuMarketplaceAttributeValue:
    return base.save(session, row)
