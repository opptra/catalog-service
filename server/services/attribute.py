"""Attribute master listing and grouping by group_label."""

from collections import OrderedDict

from sqlalchemy.orm import Session

from dto.response.attribute import (
    AttributeGroupListResponse,
    AttributeGroupResponse,
    AttributeResponse,
)
from entities.catalog.attribute_master import AttributeMaster
from repositories.catalog import attribute_master as attribute_master_repo


def list_attribute_groups(session: Session) -> AttributeGroupListResponse:
    """Return attributes grouped by ``group_label``.

    Ungrouped attributes (null label) each form their own group keyed by attribute name
    so the UI can still offer Title / Description / etc. as top-level options.
    """
    rows = attribute_master_repo.list_all(session)
    grouped: OrderedDict[str, list[AttributeMaster]] = OrderedDict()
    for row in rows:
        key = row.group_label.value if row.group_label is not None else row.name.value
        grouped.setdefault(key, []).append(row)

    return AttributeGroupListResponse(
        items=[
            AttributeGroupResponse(
                label=label,
                attributes=[
                    AttributeResponse(
                        external_id=attribute.external_id,
                        name=attribute.name.value,
                        data_type=attribute.data_type.value,
                        allows_quantity=attribute.allows_quantity,
                    )
                    for attribute in attributes
                ],
            )
            for label, attributes in grouped.items()
        ]
    )


def display_label(label: str) -> str:
    """Humanize an enum-style label for UI (``BULLET_POINTS`` → ``Bullet points``)."""
    words = label.replace("_", " ").strip().lower().split()
    if not words:
        return label
    return " ".join(word.capitalize() if index == 0 else word for index, word in enumerate(words))
