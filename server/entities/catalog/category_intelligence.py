from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Identity, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from entities.catalog.base import Base


class CategoryIntelligence(Base):
    """Category intelligence document for one category × marketplace pair."""

    __tablename__ = "category_intelligence"
    __table_args__ = (
        UniqueConstraint(
            "category_marketplace_id",
            name="category_intelligence_category_marketplace_id_key",
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    category_marketplace_id: Mapped[int] = mapped_column(
        ForeignKey("category_marketplace.id", ondelete="CASCADE"),
        nullable=False,
    )
    intelligence: Mapped[dict[str, Any]] = mapped_column(
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
