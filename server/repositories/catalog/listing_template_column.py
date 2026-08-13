from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.catalog.listing_template_column import ListingTemplateColumn
from repositories import base


def list_by_listing_template_id(
    session: Session,
    listing_template_id: int,
) -> Sequence[ListingTemplateColumn]:
    """Columns for a template, ordered by display_order then column_index."""
    return session.scalars(
        select(ListingTemplateColumn)
        .where(ListingTemplateColumn.listing_template_id == listing_template_id)
        .order_by(
            ListingTemplateColumn.display_order.asc(),
            ListingTemplateColumn.column_index.asc(),
        )
    ).all()


def save(session: Session, row: ListingTemplateColumn) -> ListingTemplateColumn:
    return base.save(session, row)


def save_all(
    session: Session, rows: Sequence[ListingTemplateColumn]
) -> list[ListingTemplateColumn]:
    return base.save_all(session, rows)
