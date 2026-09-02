"""Overlay mapping CSV onto workbook columns → listing_template_column configs.

Fill rules (per workbook column):
  - No CSV marketplace mapping → SKIP
  - Dropdown + AI_GENERATED → ENUM without source
  - Dropdown + mapped PIM field → ENUM with SKU_MASTER source
  - Non-dropdown + AI_GENERATED → AI_TEXT
  - Mapping present, not dropdown, not AI → DIRECT_MAP with SKU_MASTER source

Omits listing-column requiredness (category attribute_spec is the ingest gate).
Does not store marketplace machine keys — ``depends_on`` is parent column_index.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from listing_mapping.csv import MappingCsv, MappingRow, build_attribute_spec

from dto.listing_config import ListingColumnConfig
from entities.catalog.attribute_enums import ListingValueSourceFrom


@dataclass(frozen=True)
class OverlayResult:
    columns: list[dict[str, Any]]
    attribute_spec: dict[str, list[str]]
    warnings: list[str]


def _is_dropdown(config: dict[str, Any]) -> bool:
    if config.get("fill_type") == "ENUM":
        return True
    return bool(config.get("valid_values") or config.get("valid_values_by_parent"))


def _sku_master_source(flat_field: str) -> dict[str, str]:
    return {"from": ListingValueSourceFrom.SKU_MASTER.value, "key": flat_field}


def _index_columns(
    columns: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Map casefolded label / workbook_key → column(s). workbook_key is parse-time only."""
    index: dict[str, list[dict[str, Any]]] = {}
    for col in columns:
        config = col["config"]
        keys: list[str] = []
        label = config.get("label")
        workbook_key = col.get("workbook_key")
        if label:
            keys.append(str(label).strip())
        if workbook_key:
            keys.append(str(workbook_key).strip())
        for key in keys:
            index.setdefault(key.casefold(), []).append(col)
    return index


def _match_column(
    marketplace_name: str,
    *,
    index: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    hits = index.get(marketplace_name.casefold()) or []
    unique: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for col in hits:
        cid = id(col)
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        unique.append(col)
    if not unique:
        raise ValueError(
            f"Marketplace column {marketplace_name!r} matches no workbook column "
            "(tried label and workbook key row, case-insensitive)"
        )
    if len(unique) > 1:
        labels = [c["config"].get("label") for c in unique]
        raise ValueError(
            f"Marketplace column {marketplace_name!r} matches multiple workbook columns: {labels}"
        )
    return unique[0]


def _base_config(col: dict[str, Any]) -> dict[str, Any]:
    return {"label": col["config"]["label"]}


def _apply_row(
    col: dict[str, Any],
    row: MappingRow,
) -> dict[str, Any]:
    config = _base_config(col)
    workbook_config = col["config"]
    dropdown = _is_dropdown(workbook_config)

    if dropdown:
        config["fill_type"] = "ENUM"
        if workbook_config.get("depends_on") is not None:
            config["depends_on"] = workbook_config["depends_on"]
        if workbook_config.get("valid_values"):
            config["valid_values"] = list(workbook_config["valid_values"])
        if workbook_config.get("valid_values_by_parent"):
            config["valid_values_by_parent"] = deepcopy(workbook_config["valid_values_by_parent"])
        # AI_GENERATED on dropdown → ENUM without source (model picks from list).
        if not row.ai_generated:
            config["source"] = _sku_master_source(row.flat_field_name)
        return config

    if row.ai_generated:
        config["fill_type"] = "AI_TEXT"
        return config

    config["fill_type"] = "DIRECT_MAP"
    config["source"] = _sku_master_source(row.flat_field_name)
    return config


def _skip_config(col: dict[str, Any]) -> dict[str, Any]:
    config = _base_config(col)
    config["fill_type"] = "SKIP"
    return config


def _validate_config(config: dict[str, Any]) -> dict[str, Any]:
    """Validate via ListingColumnConfig, then omit requiredness from emitted JSON."""
    validated = ListingColumnConfig.model_validate(config)
    dumped = validated.model_dump(by_alias=True, exclude_none=True)
    dumped.pop("requiredness", None)
    for key in ("attribute_name", "slot", "source_key", "machine_key"):
        dumped.pop(key, None)
    return dumped


def overlay_columns(
    workbook_columns: list[dict[str, Any]],
    mapping: MappingCsv,
) -> OverlayResult:
    """Apply mapping CSV onto workbook-discovered columns."""
    columns = [deepcopy(col) for col in workbook_columns]
    index = _index_columns(columns)
    mapped_ids: set[int] = set()
    warnings: list[str] = []

    for row in mapping.rows:
        if not row.marketplace_column:
            continue
        col = _match_column(row.marketplace_column, index=index)
        if id(col) in mapped_ids:
            raise ValueError(
                f"Workbook column {col['config'].get('label')!r} matched by more "
                f"than one mapping row (second: {row.flat_field_name!r})"
            )
        mapped_ids.add(id(col))
        col["config"] = _validate_config(_apply_row(col, row))

    for col in columns:
        if id(col) in mapped_ids:
            continue
        col["config"] = _validate_config(_skip_config(col))

    fill_by_index = {c["column_index"]: c["config"]["fill_type"] for c in columns}
    for col in columns:
        config = col["config"]
        parent = config.get("depends_on")
        if parent is None:
            continue
        parent_fill = fill_by_index.get(parent)
        if parent_fill == "SKIP":
            warnings.append(
                f"Column {config.get('label')!r} depends_on column_index={parent} which is SKIP"
            )

    attribute_spec = build_attribute_spec(list(mapping.rows))
    return OverlayResult(
        columns=columns,
        attribute_spec=attribute_spec,
        warnings=warnings,
    )
