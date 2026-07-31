from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Identity, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from entities.user_service.base import Base


class Brand(Base):
    """Lightweight brand mirror in the user-service schema.

    Each row's ``external_id`` is independent of the catalog-service brand's
    own ``external_id``; the catalog-service ``brand.user_service_brand_id``
    column stores this row's ``external_id`` to link the two without a
    cross-database foreign key.
    """

    __tablename__ = "brand"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    external_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        unique=True,
        nullable=False,
        default=uuid4,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
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
