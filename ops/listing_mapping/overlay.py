"""Overlay mapping workbook (fill_mode + column_index) onto parsed .xlsm columns."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any

from dto.listing_config import ListingColumnConfig
from entities.catalog.attribute_enums import AttributeName, ListingValueSourceFrom
from listing_mapping.mapping_workbook import (
    FillMode,
    ListingMapRow,
    MappingWorkbook,
    build_attribute_spec,
)


@dataclass(frozen=True)
class OverlayResult:
    columns: list[dict[str, Any]]
    attribute_spec: dict[str, list[str]]
    warnings: list[str]


def _is_dropdown(config: dict[str, Any]) -> bool:
    if config.get("fill_type") == "ENUM":
        return True
    return bool(config.get("valid_values") or config.get("valid_values_by_parent"))


def _sku_master_source(pim_field: str) -> dict[str, str]:
    return {"from": ListingValueSourceFrom.SKU_MASTER.value, "key": pim_field}


_ORDINAL_GENERATION = frozenset(
    {
        AttributeName.ITEM_HIGHLIGHTS,
        AttributeName.BULLET_POINTS,
        AttributeName.IMAGE,
        AttributeName.A_PLUS,
    }
)


def _parse_generation_token(token: str) -> dict[str, Any]:
    """Parse TITLE / BULLET_POINTS:1 / IMAGE:2 → GENERATION source fields."""
    text = token.strip()
    if not text:
        raise ValueError("generation token is empty")
    if ":" in text:
        name_raw, rest = text.split(":", 1)
        name = AttributeName(name_raw.strip())
        n = int(rest.strip())
        if n < 1:
            raise ValueError(
                f"generation index/slot must be >= 1, got {n} in {token!r}"
            )
        if name in {AttributeName.IMAGE, AttributeName.A_PLUS}:
            return {
                "from": ListingValueSourceFrom.GENERATION.value,
                "attribute_name": name.value,
                "slot": n,
            }
        # Array attributes live on slot 1; :n is the list index.
        return {
            "from": ListingValueSourceFrom.GENERATION.value,
            "attribute_name": name.value,
            "slot": 1,
            "index": n,
        }
    name = AttributeName(text)
    return {
        "from": ListingValueSourceFrom.GENERATION.value,
        "attribute_name": name.value,
        "slot": 1,
    }


def _expand_generation_ordinals(rows: list[ListingMapRow]) -> list[ListingMapRow]:
    """Assign IMAGE / BULLET_POINTS / ITEM_HIGHLIGHTS slots by column_index order."""
    counts: dict[str, int] = {}
    expanded: dict[int, ListingMapRow] = {}
    for row in sorted(rows, key=lambda item: item.column_index):
        gen = (row.generation or "").strip()
        if not gen or row.fill_mode not in {FillMode.COPY_GENERATION, FillMode.IMAGE}:
            expanded[row.column_index] = row
            continue
        if ":" in gen:
            raise ValueError(
                f"column_index={row.column_index}: generation {gen!r} must be a bare "
                "name (ITEM_HIGHLIGHTS, BULLET_POINTS, IMAGE). Repeat it on each "
                "column; numbering is assigned by column_index order."
            )
        name = AttributeName(gen)
        if name in _ORDINAL_GENERATION:
            n = counts.get(name.value, 0) + 1
            counts[name.value] = n
            gen = f"{name.value}:{n}"
        else:
            gen = name.value
        expanded[row.column_index] = replace(row, generation=gen)
    return [expanded[row.column_index] for row in rows]


def _attach_enum_lists(config: dict[str, Any], workbook_config: dict[str, Any]) -> None:
    if workbook_config.get("depends_on") is not None:
        config["depends_on"] = workbook_config["depends_on"]
    if workbook_config.get("valid_values"):
        config["valid_values"] = list(workbook_config["valid_values"])
    if workbook_config.get("valid_values_by_parent"):
        config["valid_values_by_parent"] = deepcopy(
            workbook_config["valid_values_by_parent"]
        )


def _apply_row(col: dict[str, Any], row: ListingMapRow) -> dict[str, Any]:
    config: dict[str, Any] = {"label": col["config"]["label"]}
    workbook_config = col["config"]
    mode = row.fill_mode

    if mode == FillMode.SKIP:
        config["fill_type"] = "SKIP"
        return config

    if mode == FillMode.CONSTANT:
        if not row.constant_value:
            raise ValueError(
                f"column_index={row.column_index}: CONSTANT requires constant_value"
            )
        config["fill_type"] = "CONSTANT"
        config["constant_value"] = row.constant_value
        return config

    if mode == FillMode.COPY_PIM:
        if not row.pim_field:
            raise ValueError(
                f"column_index={row.column_index}: COPY_PIM requires pim_field"
            )
        if _is_dropdown(workbook_config):
            # Dropdown cells must stay ENUM; treat as ENUM with PIM source.
            config["fill_type"] = "ENUM"
            _attach_enum_lists(config, workbook_config)
            config["source"] = _sku_master_source(row.pim_field)
            return config
        config["fill_type"] = "DIRECT_MAP"
        config["source"] = _sku_master_source(row.pim_field)
        return config

    if mode in {FillMode.ENUM, FillMode.ENUM_FROM_PIM, FillMode.ENUM_AI}:
        if mode == FillMode.ENUM_FROM_PIM and not row.pim_field:
            raise ValueError(
                f"column_index={row.column_index}: ENUM_FROM_PIM requires pim_field"
            )
        if mode == FillMode.ENUM_AI and row.pim_field:
            raise ValueError(
                f"column_index={row.column_index}: ENUM_AI must leave pim_field blank"
            )
        if not _is_dropdown(workbook_config):
            raise ValueError(
                f"column_index={row.column_index}: {mode.value} but workbook column "
                f"{config['label']!r} has no dropdown/valid_values"
            )
        config["fill_type"] = "ENUM"
        _attach_enum_lists(config, workbook_config)
        if row.pim_field:
            config["source"] = _sku_master_source(row.pim_field)
        return config

    if mode == FillMode.AI_TEXT:
        if _is_dropdown(workbook_config):
            raise ValueError(
                f"column_index={row.column_index}: AI_TEXT but workbook column "
                f"{config['label']!r} is a dropdown — use ENUM"
            )
        config["fill_type"] = "AI_TEXT"
        if row.pim_field:
            config["source"] = _sku_master_source(row.pim_field)
        return config

    if mode == FillMode.COPY_GENERATION:
        if not row.generation:
            raise ValueError(
                f"column_index={row.column_index}: COPY_GENERATION requires generation"
            )
        source = _parse_generation_token(row.generation)
        if source.get("attribute_name") in {
            AttributeName.IMAGE.value,
            AttributeName.A_PLUS.value,
        }:
            raise ValueError(
                f"column_index={row.column_index}: use fill_mode IMAGE for "
                f"{row.generation!r}, not COPY_GENERATION"
            )
        config["fill_type"] = "DIRECT_MAP"
        config["source"] = source
        return config

    if mode == FillMode.IMAGE:
        if not row.generation:
            raise ValueError(
                f"column_index={row.column_index}: IMAGE requires generation"
            )
        source = _parse_generation_token(row.generation)
        if source.get("attribute_name") != AttributeName.IMAGE.value:
            raise ValueError(
                f"column_index={row.column_index}: IMAGE generation must be IMAGE, "
                f"got {row.generation!r}"
            )
        config["fill_type"] = "IMAGE"
        config["source"] = source
        return config

    raise ValueError(f"Unhandled fill_mode {mode}")


def _validate_config(config: dict[str, Any]) -> dict[str, Any]:
    validated = ListingColumnConfig.model_validate(config)
    dumped = validated.model_dump(by_alias=True, exclude_none=True)
    dumped.pop("requiredness", None)
    for key in ("attribute_name", "slot", "source_key", "machine_key"):
        dumped.pop(key, None)
    return dumped


def overlay_columns(
    workbook_columns: list[dict[str, Any]],
    mapping: MappingWorkbook,
) -> OverlayResult:
    columns = [deepcopy(col) for col in workbook_columns]
    by_index = {int(col["column_index"]): col for col in columns}
    mapped: set[int] = set()
    warnings: list[str] = []
    listing_rows = _expand_generation_ordinals(list(mapping.listing_rows))

    for row in listing_rows:
        col = by_index.get(row.column_index)
        if col is None:
            raise ValueError(
                f"mapping column_index={row.column_index} not found in workbook "
                f"(known indices: {sorted(by_index)[:20]}…)"
            )
        if row.column_index in mapped:
            raise ValueError(f"Duplicate mapping for column_index={row.column_index}")
        mapped.add(row.column_index)
        if row.fill_mode == FillMode.COPY_PIM and _is_dropdown(col["config"]):
            warnings.append(
                f"column_index={row.column_index} ({col['config'].get('label')!r}): "
                "COPY_PIM on a dropdown — emitting ENUM with PIM source"
            )
        col["config"] = _validate_config(_apply_row(col, row))

    missing = sorted(set(by_index) - mapped)
    if missing:
        preview = ", ".join(str(i) for i in missing[:20])
        more = "…" if len(missing) > 20 else ""
        raise ValueError(
            "mapping must cover every workbook column_index "
            f"(no silent SKIP). Missing: {preview}{more}"
        )

    fill_by_index = {c["column_index"]: c["config"]["fill_type"] for c in columns}
    for col in columns:
        config = col["config"]
        parent = config.get("depends_on")
        if parent is None:
            continue
        if fill_by_index.get(parent) == "SKIP":
            warnings.append(
                f"Column {config.get('label')!r} depends_on column_index={parent} which is SKIP"
            )

    return OverlayResult(
        columns=columns,
        attribute_spec=build_attribute_spec(list(mapping.pim_fields)),
        warnings=warnings,
    )
