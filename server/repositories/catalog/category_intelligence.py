from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.catalog.category_intelligence import CategoryIntelligence
from repositories import base


def get_by_category_marketplace_id(
    session: Session,
    category_marketplace_id: int,
) -> CategoryIntelligence | None:
    return session.scalar(
        select(CategoryIntelligence).where(
            CategoryIntelligence.category_marketplace_id == category_marketplace_id
        )
    )


def save(session: Session, row: CategoryIntelligence) -> CategoryIntelligence:
    return base.save(session, row)
