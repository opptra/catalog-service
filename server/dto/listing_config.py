"""Pydantic shapes for listing_template.metadata and listing_template_column.config."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from entities.catalog.attribute_enums import AttributeName, ListingFillType, ListingRequiredness


class ListingTemplateMetadata(BaseModel):
    """Offsets into the blank Amazon workbook."""

    model_config = ConfigDict(extra="forbid")

    filename: str
    sheet_name: str = "Template"
    header_label_row: int = 4
    machine_key_row: int = 5
    data_start_row: int = 7


class ListingColumnConfig(BaseModel):
    """Per-column fill rules — all type/mapping facts live here (not as SQL columns)."""

    model_config = ConfigDict(extra="forbid")

    fill_type: ListingFillType
    requiredness: ListingRequiredness = ListingRequiredness.OPTIONAL
    label: str
    machine_key: str | None = None
    attribute_name: AttributeName | None = None
    slot: int | None = Field(default=None, ge=1)
    source_key: str | None = None
    constant_value: str | None = None
    valid_values: list[str] | None = None

    @model_validator(mode="after")
    def _check_mapping_keys(self) -> ListingColumnConfig:
        has_attr = self.attribute_name is not None
        has_source = bool(self.source_key)
        if (
            has_attr
            and has_source
            and self.fill_type
            in (
                ListingFillType.LLM_TEXT,
                ListingFillType.IMAGE,
                ListingFillType.DIRECT_MAP,
            )
        ):
            raise ValueError(
                "attribute_name and source_key cannot both be set for job/PIM copy fill types"
            )
        if self.fill_type in (
            ListingFillType.LLM_TEXT,
            ListingFillType.IMAGE,
        ) and (self.attribute_name is None or self.slot is None):
            raise ValueError(f"{self.fill_type} requires attribute_name and slot")
        if self.fill_type == ListingFillType.DIRECT_MAP and not self.source_key:
            raise ValueError("DIRECT_MAP requires source_key")
        if self.fill_type == ListingFillType.CONSTANT and self.constant_value is None:
            raise ValueError("CONSTANT requires constant_value")
        if self.fill_type == ListingFillType.ENUM and not self.valid_values:
            raise ValueError("ENUM requires non-empty valid_values")
        return self
