from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Identity, Index, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from entities.catalog.base import Base


class SkuMaster(Base):
    __tablename__ = "sku_master"
    __table_args__ = (
        Index("idx_sku_master_category", "category_id"),
        Index("idx_sku_master_attributes", "attributes", postgresql_using="gin"),
        Index(
            "idx_sku_master_live",
            "category_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # JSONB PIM bag. Services/pipelines must not read or assign this column —
    # use services.product_attributes (for_sku / facts_for_sku / apply_write).
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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
