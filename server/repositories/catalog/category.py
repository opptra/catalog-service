from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import exists, select, text
from sqlalchemy.orm import Session

from entities.catalog.category import Category
from entities.catalog.category_closure import CategoryClosure
from repositories import base

# Fetch one extra leaf so callers can detect has_more without a COUNT(*).
_LEAF_PAGE_SQL = text(
    """
    WITH leaves AS (
        SELECT c.id, c.external_id, c.name
        FROM categories c
        WHERE NOT EXISTS (
            SELECT 1
            FROM category_closure child
            WHERE child.ancestor_id = c.id
              AND child.depth = 1
        )
        ORDER BY c.name ASC, c.id ASC
        LIMIT :fetch_limit OFFSET :offset
    )
    SELECT
        l.id AS leaf_id,
        l.external_id AS leaf_external_id,
        l.name AS leaf_name,
        a.external_id AS ancestor_external_id,
        a.name AS ancestor_name,
        cc.depth AS depth
    FROM leaves l
    JOIN category_closure cc ON cc.descendant_id = l.id
    JOIN categories a ON a.id = cc.ancestor_id
    ORDER BY l.name ASC, l.id ASC, cc.depth DESC
    """
)


@dataclass(frozen=True, slots=True)
class CategoryPathNodeRow:
    external_id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class LeafCategoryRow:
    external_id: UUID
    name: str
    path: tuple[CategoryPathNodeRow, ...]


def get_by_id(session: Session, category_id: int) -> Category | None:
    return session.get(Category, category_id)


def get_by_external_id(session: Session, external_id: UUID) -> Category | None:
    return session.scalar(select(Category).where(Category.external_id == external_id))


def list_by_ids(session: Session, category_ids: Sequence[int]) -> Sequence[Category]:
    if not category_ids:
        return []
    return session.scalars(select(Category).where(Category.id.in_(category_ids))).all()


def list_roots_by_name(session: Session, name: str) -> Sequence[Category]:
    """Categories with the given name that have no parent (depth-1 ancestor)."""
    has_parent = exists().where(
        CategoryClosure.descendant_id == Category.id,
        CategoryClosure.depth == 1,
    )
    return session.scalars(
        select(Category).where(Category.name == name, ~has_parent).order_by(Category.id.asc())
    ).all()


def list_children_by_name(session: Session, parent_id: int, name: str) -> Sequence[Category]:
    """Direct children of ``parent_id`` with the given name."""
    return session.scalars(
        select(Category)
        .join(
            CategoryClosure,
            CategoryClosure.descendant_id == Category.id,
        )
        .where(
            CategoryClosure.ancestor_id == parent_id,
            CategoryClosure.depth == 1,
            Category.name == name,
        )
        .order_by(Category.id.asc())
    ).all()


def save(session: Session, category: Category) -> Category:
    return base.save(session, category)


def list_leaf_categories_with_paths(
    session: Session,
    *,
    offset: int,
    limit: int,
) -> tuple[list[LeafCategoryRow], bool]:
    """Return a page of leaf categories with root→leaf paths.

    A leaf is any category with no depth-1 descendants in ``category_closure``.
    Paths are built in one SQL round-trip; ``has_more`` uses limit+1.
    """
    if limit < 1:
        return [], False

    rows = session.execute(
        _LEAF_PAGE_SQL,
        {"fetch_limit": limit + 1, "offset": offset},
    ).all()

    ordered_leaf_ids: list[int] = []
    leaf_external_ids: dict[int, UUID] = {}
    leaf_names: dict[int, str] = {}
    paths: dict[int, list[CategoryPathNodeRow]] = {}

    for row in rows:
        leaf_id = int(row.leaf_id)
        if leaf_id not in leaf_names:
            ordered_leaf_ids.append(leaf_id)
            leaf_external_ids[leaf_id] = UUID(str(row.leaf_external_id))
            leaf_names[leaf_id] = str(row.leaf_name)
            paths[leaf_id] = []
        paths[leaf_id].append(
            CategoryPathNodeRow(
                external_id=UUID(str(row.ancestor_external_id)),
                name=str(row.ancestor_name),
            )
        )

    has_more = len(ordered_leaf_ids) > limit
    page_ids = ordered_leaf_ids[:limit]

    return [
        LeafCategoryRow(
            external_id=leaf_external_ids[leaf_id],
            name=leaf_names[leaf_id],
            path=tuple(paths[leaf_id]),
        )
        for leaf_id in page_ids
    ], has_more
