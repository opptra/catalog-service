from collections.abc import Sequence
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.catalog.sku_marketplace_attribute_value import SkuMarketplaceAttributeValue
from repositories import base

# Stable namespace for deterministic value external_ids (not a secret).
_VALUE_EXTERNAL_ID_NAMESPACE = UUID("6f0a2c8e-4b1d-4e9a-9f3c-7a5d2e1b0c84")


def lineage_external_id(
    *,
    sku_id: int,
    marketplace_id: int,
    attribute_id: int,
    slot: int,
    sku_generation_job_id: int,
) -> UUID:
    """external_id for one version lineage — unique per the five identity keys."""
    return uuid5(
        _VALUE_EXTERNAL_ID_NAMESPACE,
        (f"{sku_id}:{marketplace_id}:{attribute_id}:{slot}:{sku_generation_job_id}"),
    )


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


def get_by_external_id_and_version(
    session: Session, external_id: UUID, version: int
) -> SkuMarketplaceAttributeValue | None:
    return session.scalar(
        select(SkuMarketplaceAttributeValue).where(
            SkuMarketplaceAttributeValue.external_id == external_id,
            SkuMarketplaceAttributeValue.version == version,
        )
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
