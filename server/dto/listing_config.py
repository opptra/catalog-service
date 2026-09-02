"""Pydantic shapes for listing_template.metadata and listing_template_column.config."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from entities.catalog.attribute_enums import (
    AttributeName,
    ListingFillType,
    ListingRequiredness,
    ListingValueSourceFrom,
)


class ListingTemplateMetadata(BaseModel):
    """Offsets into the blank Amazon workbook."""

    model_config = ConfigDict(extra="forbid")

    filename: str
    sheet_name: str = "Template"
    header_label_row: int = 4
    machine_key_row: int = 5
    data_start_row: int = 7


class ListingValueSource(BaseModel):
    """Where fill reads a value from (GENERATION job bag or SKU master PIM).

    For list-valued generation attributes (e.g. BULLET_POINTS stored as one JSON
    array on slot 1), ``index`` selects the 1-based array element. Without
    ``index``, a JSON array is joined with spaces (e.g. BACKEND_KEYWORDS →
    Generic Keyword).

    For SKU_MASTER, ``key`` is the exact ``sku_master.attributes`` field name.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # ``from`` is reserved in Python; JSON key remains ``"from"``.
    from_: ListingValueSourceFrom = Field(alias="from")
    attribute_name: AttributeName | None = None
    slot: int | None = Field(default=None, ge=1)
    index: int | None = Field(default=None, ge=1)
    key: str | None = None

    @model_validator(mode="after")
    def _check_source_fields(self) -> ListingValueSource:
        if self.from_ == ListingValueSourceFrom.GENERATION:
            if self.attribute_name is None or self.slot is None:
                raise ValueError("source.from=GENERATION requires attribute_name and slot")
            if self.key:
                raise ValueError("source.from=GENERATION must not set key")
        elif self.from_ == ListingValueSourceFrom.SKU_MASTER:
            if not self.key or not self.key.strip():
                raise ValueError("source.from=SKU_MASTER requires key")
            if self.attribute_name is not None or self.slot is not None or self.index is not None:
                raise ValueError("source.from=SKU_MASTER must not set attribute_name/slot/index")
        return self


class ListingColumnConfig(BaseModel):
    """Per-column fill rules — all type/mapping facts live here (not as SQL columns).

    ``fill_type`` = how to fill. ``source`` = where to read (when copying / imaging).
    ``depends_on`` = parent Excel ``column_index`` (not a marketplace field name).
    """

    model_config = ConfigDict(extra="forbid")

    fill_type: ListingFillType
    requiredness: ListingRequiredness = ListingRequiredness.OPTIONAL
    label: str

    constant_value: str | None = None
    source: ListingValueSource | None = None

    # ENUM
    valid_values: list[str] | None = None
    depends_on: int | None = Field(default=None, ge=1)
    valid_values_by_parent: dict[str, list[str]] | None = None

    # Legacy flat fields — accepted on read, normalized into ``source``.
    attribute_name: AttributeName | None = None
    slot: int | None = Field(default=None, ge=1)
    source_key: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _lift_legacy_source(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        # Marketplace machine keys are parse-time only — never stored on config.
        out.pop("machine_key", None)
        depends_on = out.get("depends_on")
        if isinstance(depends_on, str):
            text = depends_on.strip()
            if text.isdigit():
                out["depends_on"] = int(text)
            else:
                raise ValueError(
                    "depends_on must be a parent column_index (int); "
                    f"got marketplace key {depends_on!r} — regenerate listing columns"
                )
        if out.get("source") is None:
            attr = out.get("attribute_name")
            slot = out.get("slot")
            key = out.get("source_key")
            if attr is not None and slot is not None:
                out["source"] = {
                    "from": ListingValueSourceFrom.GENERATION.value,
                    "attribute_name": attr,
                    "slot": slot,
                }
            elif key:
                out["source"] = {
                    "from": ListingValueSourceFrom.SKU_MASTER.value,
                    "key": key,
                }
        return out

    @model_validator(mode="after")
    def _check_mapping_keys(self) -> ListingColumnConfig:
        fill = self.fill_type

        if fill == ListingFillType.SKIP:
            return self

        if fill == ListingFillType.CONSTANT:
            if self.constant_value is None:
                raise ValueError("CONSTANT requires constant_value")
            return self

        if fill == ListingFillType.ENUM:
            has_flat = bool(self.valid_values)
            has_by_parent = bool(self.valid_values_by_parent)
            if not has_flat and not has_by_parent:
                raise ValueError("ENUM requires valid_values and/or valid_values_by_parent")
            if self.valid_values_by_parent is not None and self.depends_on is None:
                raise ValueError("valid_values_by_parent requires depends_on")
            if self.source is not None and self.source.from_ != ListingValueSourceFrom.SKU_MASTER:
                raise ValueError("ENUM source (exact-match hint) must be from=SKU_MASTER")
            return self

        if fill == ListingFillType.DIRECT_MAP:
            if self.source is None:
                raise ValueError(f"{fill} requires source")
            return self

        if fill == ListingFillType.AI_TEXT:
            # Free-text fill-time generation — label is the prompt hint.
            if self.source is not None:
                raise ValueError("AI_TEXT must not set source")
            if self.constant_value is not None:
                raise ValueError("AI_TEXT must not set constant_value")
            return self

        if fill == ListingFillType.IMAGE:
            if self.source is None:
                raise ValueError("IMAGE requires source")
            if self.source.from_ != ListingValueSourceFrom.GENERATION:
                raise ValueError("IMAGE source must be from=GENERATION")
            if self.source.attribute_name != AttributeName.IMAGE:
                raise ValueError("IMAGE source.attribute_name must be IMAGE")
            return self

        return self
