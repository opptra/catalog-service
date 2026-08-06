from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Identity, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from entities.catalog.base import Base


class CategoryMarketplace(Base):
    """Category intelligence scoped to a marketplace (one row per category × marketplace)."""

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
    category_intelligence: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
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
