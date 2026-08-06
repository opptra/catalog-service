from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Identity, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from entities.catalog.base import Base


class Job(Base):
    __tablename__ = "job"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    external_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        unique=True,
        nullable=False,
        default=uuid4,
    )
    # No DB-level FK: users live in a separate database. This stores the
    # user's external_id, resolved via the user repository/service.
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    # Stores brand.external_id (not brand.id). Lets list/filter jobs by brand
    # without joining through SKUs.
    brand_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    job_type: Mapped[str] = mapped_column(Text, nullable=False, default="GENERATION")
    marketplace_id: Mapped[int | None] = mapped_column(
        ForeignKey("marketplace.id"),
        nullable=True,
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
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
