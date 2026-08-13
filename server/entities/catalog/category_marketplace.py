from datetime import datetime

from sqlalchemy import ForeignKey, Identity, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from entities.catalog.base import Base


class CategoryMarketplace(Base):
    """Junction: one row per category × marketplace.

    ``category_intelligence`` stays as a DB column for production readers; this
    branch loads intelligence from the ``category_intelligence`` table instead.
    """

    __tablename__ = "category_marketplace"
    __table_args__ = (
        UniqueConstraint(
            "marketplace_id",
            "category_id",
            name="category_marketplace_marketplace_id_category_id_key",
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    marketplace_id: Mapped[int] = mapped_column(ForeignKey("marketplace.id"), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
