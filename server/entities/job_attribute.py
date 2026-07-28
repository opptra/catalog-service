from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Identity, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from entities.base import Base


class JobAttribute(Base):
    __tablename__ = "job_attribute"
    __table_args__ = (
        UniqueConstraint("job_id", "attribute_id", name="job_attribute_job_id_attribute_id_key"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    external_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        unique=True,
        nullable=False,
        default=uuid4,
    )
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id"), nullable=False)
    attribute_id: Mapped[int] = mapped_column(ForeignKey("attribute_master.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
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
