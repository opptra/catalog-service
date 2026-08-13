from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Identity, Integer, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from entities.catalog.base import Base


class ListingTemplateColumn(Base):
    """One Excel column rule for a listing template.

    Query/sort spine only: column_index + resolve_stage. All type/mapping details
    live in ``config`` (no redundant SQL columns for fill_type/requiredness/etc.).
    """

    __tablename__ = "listing_template_column"
    __table_args__ = (
        UniqueConstraint(
            "listing_template_id",
            "column_index",
            name="listing_template_column_template_id_column_index_key",
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    listing_template_id: Mapped[int] = mapped_column(
        ForeignKey("listing_template.id", ondelete="CASCADE"),
        nullable=False,
    )
    column_index: Mapped[int] = mapped_column(Integer, nullable=False)
    resolve_stage: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(
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
