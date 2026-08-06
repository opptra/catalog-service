from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.catalog.category_marketplace import CategoryMarketplace


def get_by_marketplace_and_category(
    session: Session,
    marketplace_id: int,
    category_id: int,
) -> CategoryMarketplace | None:
    return session.scalar(
        select(CategoryMarketplace).where(
            CategoryMarketplace.marketplace_id == marketplace_id,
            CategoryMarketplace.category_id == category_id,
        )
    )
