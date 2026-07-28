from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Identity, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from entities.base import Base


class Job(Base):
    __tablename__ = "job"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    external_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        unique=True,
        nullable=False,
        default=uuid4,
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    marketplace_id: Mapped[int] = mapped_column(ForeignKey("marketplace.id"), nullable=False)
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
