from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Identity, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from entities.catalog.base import Base


class ListingTemplate(Base):
    """Blank Amazon listing workbook for one category × marketplace pair."""

    __tablename__ = "listing_template"
    __table_args__ = (
        UniqueConstraint(
            "category_marketplace_id",
            name="listing_template_category_marketplace_id_key",
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    category_marketplace_id: Mapped[int] = mapped_column(
        ForeignKey("category_marketplace.id", ondelete="CASCADE"),
        nullable=False,
    )
    gcs_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
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
