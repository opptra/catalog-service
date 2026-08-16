from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.catalog.listing_template import ListingTemplate
from repositories import base


def get_by_id(session: Session, template_id: int) -> ListingTemplate | None:
    return session.get(ListingTemplate, template_id)


def get_by_category_marketplace_id(
    session: Session,
    category_marketplace_id: int,
) -> ListingTemplate | None:
    return session.scalar(
        select(ListingTemplate).where(
            ListingTemplate.category_marketplace_id == category_marketplace_id
        )
    )


def save(session: Session, row: ListingTemplate) -> ListingTemplate:
    return base.save(session, row)
