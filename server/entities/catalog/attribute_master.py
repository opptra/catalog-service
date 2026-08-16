from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Enum, Identity
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from entities.catalog.attribute_enums import (
    AttributeDataType,
    AttributeGroupLabel,
    AttributeName,
)
from entities.catalog.base import Base


def _str_enum_values(enum_cls: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_cls]


class AttributeMaster(Base):
    __tablename__ = "attribute_master"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    external_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        unique=True,
        nullable=False,
        default=uuid4,
    )
    name: Mapped[AttributeName] = mapped_column(
        Enum(
            AttributeName,
            name="attribute_name",
            values_callable=_str_enum_values,
            native_enum=False,
            validate_strings=True,
        ),
        unique=True,
        nullable=False,
    )
    data_type: Mapped[AttributeDataType] = mapped_column(
        Enum(
            AttributeDataType,
            name="attribute_data_type",
            values_callable=_str_enum_values,
            native_enum=False,
            validate_strings=True,
        ),
        nullable=False,
    )
    allows_quantity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    group_label: Mapped[AttributeGroupLabel | None] = mapped_column(
        Enum(
            AttributeGroupLabel,
            name="attribute_group_label",
            values_callable=_str_enum_values,
            native_enum=False,
            validate_strings=True,
        ),
        nullable=True,
    )
