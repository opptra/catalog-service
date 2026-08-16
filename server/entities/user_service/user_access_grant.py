from datetime import datetime

from sqlalchemy import ForeignKey, Identity, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from entities.user_service.base import Base


class UserAccessGrant(Base):
    """Maps a user's access to a given brand + application at a role.

    A single row grants one ``user`` the ``role`` for one ``application``
    within one ``brand``. The role is an internal concept (not surfaced on the
    UI); for now every grant uses the ``USER`` role.
    """

    __tablename__ = "user_access_grants"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "brand_id",
            "application_id",
            name="uq_user_access_grant",
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    brand_id: Mapped[int] = mapped_column(
        ForeignKey("brand.id", ondelete="CASCADE"),
        nullable=False,
    )
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id"),
        nullable=False,
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
