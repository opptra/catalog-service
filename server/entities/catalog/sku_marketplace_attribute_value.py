from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, Identity, Integer, Text, UniqueConstraint, func
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
    # Stable across versions of the same slot — not unique alone; app mints/copies it.
    external_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    sku_id: Mapped[int] = mapped_column(nullable=False)
    marketplace_id: Mapped[int] = mapped_column(ForeignKey("marketplace.id"), nullable=False)
    attribute_id: Mapped[int] = mapped_column(ForeignKey("attribute_master.id"), nullable=False)
    slot: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    sku_job_id: Mapped[int] = mapped_column(ForeignKey("sku_job.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
