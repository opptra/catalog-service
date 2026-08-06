from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.catalog.sku_master import SkuMaster
from repositories import base


def get_by_id(session: Session, sku_id: int) -> SkuMaster | None:
    return session.get(SkuMaster, sku_id)


def get_live_by_attribute_sku_id(session: Session, sku_id: str) -> SkuMaster | None:
    """Look up a live SKU by the string ``attributes.sku_id`` value (not the table PK)."""
    return session.scalar(
        select(SkuMaster).where(
            SkuMaster.deleted_at.is_(None),
            SkuMaster.attributes["sku_id"].astext == sku_id,
        )
    )


def save(session: Session, sku: SkuMaster) -> SkuMaster:
    return base.save(session, sku)


def save_all(session: Session, skus: Sequence[SkuMaster]) -> list[SkuMaster]:
    return base.save_all(session, skus)


def list_by_ids(session: Session, sku_ids: Sequence[int]) -> Sequence[SkuMaster]:
    """Return live SKUs for the given ids (soft-deleted rows are excluded)."""
    if not sku_ids:
        return []
    return session.scalars(
        select(SkuMaster).where(
            SkuMaster.id.in_(sku_ids),
            SkuMaster.deleted_at.is_(None),
        )
    ).all()


def list_live_by_category(session: Session, category_id: int) -> Sequence[SkuMaster]:
    return session.scalars(
        select(SkuMaster).where(
            SkuMaster.category_id == category_id,
            SkuMaster.deleted_at.is_(None),
        )
    ).all()
