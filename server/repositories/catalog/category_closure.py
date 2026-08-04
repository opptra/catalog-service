from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.catalog.category_closure import CategoryClosure


def get_parent_id(session: Session, category_id: int) -> int | None:
    return session.scalar(
        select(CategoryClosure.ancestor_id).where(
            CategoryClosure.descendant_id == category_id,
            CategoryClosure.depth == 1,
        )
    )


def list_child_ids(session: Session, category_id: int) -> Sequence[int]:
    return session.scalars(
        select(CategoryClosure.descendant_id).where(
            CategoryClosure.ancestor_id == category_id,
            CategoryClosure.depth == 1,
        )
    ).all()


def is_leaf(session: Session, category_id: int) -> bool:
    child = session.scalar(
        select(CategoryClosure.descendant_id)
        .where(
            CategoryClosure.ancestor_id == category_id,
            CategoryClosure.depth == 1,
        )
        .limit(1)
    )
    return child is None
