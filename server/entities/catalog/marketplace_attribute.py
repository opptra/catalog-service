from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Identity, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from entities.catalog.base import Base


class MarketplaceAttribute(Base):
    """Which attributes a marketplace offers, plus generation/UI rules in ``config``."""

    __tablename__ = "marketplace_attribute"
    __table_args__ = (
        UniqueConstraint(
            "marketplace_id",
            "attribute_id",
            name="marketplace_attribute_marketplace_id_attribute_id_key",
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    marketplace_id: Mapped[int] = mapped_column(ForeignKey("marketplace.id"), nullable=False)
    attribute_id: Mapped[int] = mapped_column(ForeignKey("attribute_master.id"), nullable=False)
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
