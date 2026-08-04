from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.catalog.category import Category


def get_by_id(session: Session, category_id: int) -> Category | None:
    return session.get(Category, category_id)


def list_by_ids(session: Session, category_ids: Sequence[int]) -> Sequence[Category]:
    if not category_ids:
        return []
    return session.scalars(select(Category).where(Category.id.in_(category_ids))).all()
