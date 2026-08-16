from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.catalog.category_closure import CategoryClosure
from repositories import base


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


def list_ancestor_rows(session: Session, category_id: int) -> Sequence[CategoryClosure]:
    """All closure rows where ``category_id`` is the descendant (self + ancestors)."""
    return session.scalars(
        select(CategoryClosure).where(CategoryClosure.descendant_id == category_id)
    ).all()


def save_all(session: Session, rows: Sequence[CategoryClosure]) -> list[CategoryClosure]:
    return base.save_all(session, rows)
