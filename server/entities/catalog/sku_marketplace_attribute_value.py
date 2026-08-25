from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Identity, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from entities.catalog.base import Base


class SkuMarketplaceAttributeValue(Base):
    __tablename__ = "sku_marketplace_attribute_value"
    __table_args__ = (
        UniqueConstraint(
            "sku_id",
            "marketplace_id",
            "attribute_id",
            "slot",
            "sku_generation_job_id",
            "version",
            name="sku_marketplace_attribute_value_slot_version_key",
        ),
        UniqueConstraint(
            "external_id",
            "version",
            name="sku_marketplace_attribute_value_external_id_version_key",
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    # Deterministic per (sku, marketplace, attribute, slot, sku_generation_job).
    # Shared across versions of that lineage — not unique alone.
    external_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    sku_id: Mapped[int] = mapped_column(ForeignKey("sku_master.id"), nullable=False)
    marketplace_id: Mapped[int] = mapped_column(ForeignKey("marketplace.id"), nullable=False)
    attribute_id: Mapped[int] = mapped_column(ForeignKey("attribute_master.id"), nullable=False)
    slot: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    # Exact prompt that produced this value version (null for rows written before this column).
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Image-slot product-data verification snapshot (null = never verified).
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    sku_generation_job_id: Mapped[int] = mapped_column(
        ForeignKey("sku_generation_job.id"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
