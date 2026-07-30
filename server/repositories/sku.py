from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.sku import Sku


def get_by_id(session: Session, sku_id: int) -> Sku | None:
    return session.get(Sku, sku_id)


def get_by_external_id(session: Session, external_id: UUID) -> Sku | None:
    return session.scalar(select(Sku).where(Sku.external_id == external_id))


def get_by_product_key(session: Session, product_key: str) -> Sku | None:
    return session.scalar(select(Sku).where(Sku.product_key == product_key))


def get_or_create_by_product_key(
    session: Session,
    *,
    product_key: str,
    name: str,
    brand_id: int | None = None,
    primary_image_url: str | None = None,
    pim_payload: dict[str, Any] | None = None,
    status: str = "draft",
) -> Sku:
    existing = get_by_product_key(session, product_key)
    if existing is not None:
        # Refresh mutable catalog fields from the latest PIM snapshot.
        existing.name = name
        if brand_id is not None:
            existing.brand_id = brand_id
        if primary_image_url is not None:
            existing.primary_image_url = primary_image_url
        if pim_payload is not None:
            existing.pim_payload = pim_payload
        return existing

    sku = Sku(
        product_key=product_key,
        name=name,
        brand_id=brand_id,
        primary_image_url=primary_image_url,
        pim_payload=pim_payload,
        status=status,
    )
    session.add(sku)
    session.flush()
    return sku
