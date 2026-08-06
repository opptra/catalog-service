from uuid import UUID

from pydantic import BaseModel, Field


class AttributeResponse(BaseModel):
    external_id: UUID
    name: str
    data_type: str
    allows_quantity: bool


class AttributeGroupResponse(BaseModel):
    """Attributes sharing a group_label (or a single attribute when ungrouped)."""

    label: str = Field(description="Group label key used for selection and grouping.")
    attributes: list[AttributeResponse] = Field(
        description="Members of this group (available for future expandable UI).",
    )


class AttributeGroupListResponse(BaseModel):
    items: list[AttributeGroupResponse]
