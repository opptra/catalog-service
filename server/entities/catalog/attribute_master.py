from uuid import UUID, uuid4

from sqlalchemy import Boolean, Identity, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from entities.base import Base


class AttributeMaster(Base):
    __tablename__ = "attribute_master"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    external_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        unique=True,
        nullable=False,
        default=uuid4,
    )
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    data_type: Mapped[str] = mapped_column(Text, nullable=False)
    allows_quantity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    group_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_group: Mapped[str | None] = mapped_column(Text, nullable=True)
