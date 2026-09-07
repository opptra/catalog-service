"""Render human-run SQL for attribute_spec + listing_template metadata + columns."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from dto.listing_config import ListingTemplateMetadata
from utils.listing_template_columns import WorkbookLayout, _json_sql, _sql_str


@dataclass(frozen=True)
class ApplyIds:
    """IDs captured by the CLI and written as SQL literals (no client binds)."""

    category_external_id: str
    marketplace_external_id: str
    gcs_object_key: str


def _json_literal(value: object) -> str:
    return _sql_str(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _as_jsonb(sql_expr: str) -> str:
    """CAST(... AS jsonb) so JDBC clients do not treat ::jsonb as a :jsonb bind."""
    return f"CAST({sql_expr} AS jsonb)"


def _as_uuid_sql(value: str) -> str:
    return f"CAST({_sql_str(value)} AS uuid)"


def _as_text_sql(value: str) -> str:
    return f"CAST({_sql_str(value)} AS text)"


def _jsonb_union_array_sql(*, existing_key: str, incoming: list[str]) -> str:
    """Existing jsonb string/int array ∪ incoming names; keep existing order first."""
    incoming_sql = _json_literal(incoming)
    empty = _as_jsonb("'[]'")
    return (
        f"(SELECT COALESCE(jsonb_agg(elem ORDER BY ord), {empty})\n"
        "        FROM (\n"
        "            SELECT DISTINCT ON (elem) elem, ord\n"
        "            FROM (\n"
        "                SELECT e.elem, e.ord\n"
        f"                FROM jsonb_array_elements(\n"
        f"                    COALESCE(attribute_spec->'{existing_key}', {empty})\n"
        "                ) WITH ORDINALITY AS e(elem, ord)\n"
        "                UNION ALL\n"
        "                SELECT e.elem, 1000000 + e.ord\n"
        f"                FROM jsonb_array_elements({_as_jsonb(incoming_sql)})\n"
        "                    WITH ORDINALITY AS e(elem, ord)\n"
        "            ) u\n"
        "            ORDER BY elem, ord\n"
        "        ) d)"
    )


def _merge_attribute_spec_sql(
    attribute_spec: dict[str, list[str]],
    *,
    category_id_sql: str,
) -> list[str]:
    allowed = list(attribute_spec.get("allowed") or [])
    mandatory = list(attribute_spec.get("mandatory") or [])
    return [
        "-- Merge pim_contract into the category's existing attribute_spec.",
        "-- Keeps names already on the category; appends new allowed/mandatory.",
        "-- Does not replace or drop existing entries.",
        "UPDATE categories",
        f"SET attribute_spec = COALESCE(attribute_spec, {_as_jsonb("'{}'")}) || jsonb_build_object(",
        f"    'allowed', {_jsonb_union_array_sql(existing_key='allowed', incoming=allowed)},",
        f"    'mandatory', {_jsonb_union_array_sql(existing_key='mandatory', incoming=mandatory)}",
        ")",
        f"WHERE external_id = {category_id_sql};",
    ]


def render_mapping_sql(
    *,
    columns: list[dict[str, Any]],
    attribute_spec: dict[str, list[str]],
    layout: WorkbookLayout,
    xlsm_name: str,
    mapping_name: str,
    marketplace_id: str,
    apply_ids: ApplyIds,
    warnings: list[str] | None = None,
) -> str:
    by_stage: dict[int, int] = defaultdict(int)
    by_fill: dict[str, int] = defaultdict(int)
    enum_with_source = 0
    enum_without_source = 0
    for col in columns:
        by_stage[col["resolve_stage"]] += 1
        fill = col["config"]["fill_type"]
        by_fill[fill] += 1
        if fill == "ENUM":
            if col["config"].get("source"):
                enum_with_source += 1
            else:
                enum_without_source += 1

    metadata = ListingTemplateMetadata(
        filename=xlsm_name,
        sheet_name=layout.sheet_name,
        header_label_row=layout.header_label_row,
        machine_key_row=layout.machine_key_row,
        data_start_row=layout.data_start_row,
    )
    metadata_json = metadata.model_dump()
    attribute_spec_json = {
        "allowed": list(attribute_spec.get("allowed") or []),
        "mandatory": list(attribute_spec.get("mandatory") or []),
    }

    if not columns:
        raise ValueError("No listing columns to insert")

    category_id_sql = _as_uuid_sql(apply_ids.category_external_id)
    marketplace_id_sql = _as_uuid_sql(apply_ids.marketplace_external_id)
    gcs_key_sql = _as_text_sql(apply_ids.gcs_object_key)

    lines = [
        "-- Human-run only. Agent does not apply this against any database.",
        f"-- Generated from {xlsm_name} + {mapping_name} by ops.listing_mapping",
        f"-- Marketplace adapter: {marketplace_id}",
        "--",
        "-- IDs were captured by the CLI and inlined (no SQL-client binds).",
        f"--   category_external_id    = {apply_ids.category_external_id}",
        f"--   marketplace_external_id = {apply_ids.marketplace_external_id}",
        f"--   gcs_object_key          = {apply_ids.gcs_object_key or '(empty)'}",
        "--",
        "-- Re-generate (from repo root; omit ID flags to be prompted):",
        "--   PYTHONPATH=ops plus server python -m listing_mapping \\",
        "--     --mapping /path/to/mapping.xlsx \\",
        f"--     --marketplace {marketplace_id} \\",
        f"--     --xlsm /path/to/{xlsm_name} \\",
        "--     --out tmp/listing_mapping/sql/<marketplace>_listing_mapping.sql \\",
        f"--     --category-external-id {apply_ids.category_external_id} \\",
        f"--     --marketplace-external-id {apply_ids.marketplace_external_id} \\",
        f"--     --gcs-object-key {apply_ids.gcs_object_key}",
        "--",
        (
            f"-- Workbook layout ({marketplace_id}): sheet={layout.sheet_name!r} "
            f"labels={layout.header_label_row} keys={layout.machine_key_row} "
            f"data={layout.data_start_row}; "
            f"valid_values={layout.valid_values_sheet!r}, "
            f"dropdown_lists={layout.dropdown_lists_sheet!r}."
        ),
        "--",
        "-- Prerequisites:",
        "--   1) Category row exists (import path / UI).",
        "--   2) Marketplace row exists.",
        "--   3) Prefer uploading the blank .xlsm via the listing-template API so",
        "--      category_marketplace + listing_template already exist; then this",
        "--      script merges attribute_spec and refreshes metadata and columns.",
        "--",
        f"-- Columns: {len(columns)} | fill_types={dict(by_fill)} |",
        f"-- ENUM with source={enum_with_source} without source={enum_without_source} |",
        f"-- resolve_stages={dict(sorted(by_stage.items()))}",
        "--",
        "-- No listing-column requiredness: category attribute_spec.mandatory is the gate.",
    ]
    for warning in warnings or []:
        lines.append(f"-- WARNING: {warning}")

    cm_from = (
        "FROM category_marketplace cm\n"
        "JOIN categories c ON c.id = cm.category_id\n"
        "JOIN marketplace m ON m.id = cm.marketplace_id\n"
        f"WHERE c.external_id = {category_id_sql}\n"
        f"  AND m.external_id = {marketplace_id_sql}"
    )
    lt_from = (
        "FROM listing_template lt\n"
        "JOIN category_marketplace cm ON cm.id = lt.category_marketplace_id\n"
        "JOIN categories c ON c.id = cm.category_id\n"
        "JOIN marketplace m ON m.id = cm.marketplace_id\n"
        f"WHERE c.external_id = {category_id_sql}\n"
        f"  AND m.external_id = {marketplace_id_sql}"
    )

    lines.extend(
        [
            "",
            "BEGIN;",
            "",
            "-- ---------------------------------------------------------------------------",
            "-- 1) Category PIM allow/mandatory list (from mapping pim_contract)",
            "-- ---------------------------------------------------------------------------",
            *_merge_attribute_spec_sql(
                attribute_spec_json, category_id_sql=category_id_sql
            ),
            "",
            "-- ---------------------------------------------------------------------------",
            "-- 2) Ensure category × marketplace junction exists",
            "-- ---------------------------------------------------------------------------",
            "INSERT INTO category_marketplace (marketplace_id, category_id)",
            "SELECT m.id, c.id",
            "FROM marketplace m",
            "CROSS JOIN categories c",
            f"WHERE m.external_id = {marketplace_id_sql}",
            f"  AND c.external_id = {category_id_sql}",
            "ON CONFLICT (marketplace_id, category_id) DO NOTHING;",
            "",
            "-- ---------------------------------------------------------------------------",
            "-- 3) Delete any existing listing columns for this category × marketplace",
            "-- ---------------------------------------------------------------------------",
            "DELETE FROM listing_template_column",
            "WHERE listing_template_id IN (",
            "    SELECT lt.id",
            f"    {lt_from}",
            ");",
            "",
            "-- ---------------------------------------------------------------------------",
            "-- 4) Ensure listing_template row + workbook offsets (metadata)",
            "--    If the row is missing, gcs_object_key must point at the blank .xlsm.",
            "-- ---------------------------------------------------------------------------",
            "INSERT INTO listing_template (category_marketplace_id, gcs_object_key, metadata)",
            f"SELECT cm.id, {gcs_key_sql}, {_as_jsonb("'{}'")}",
            f"{cm_from}",
            "  AND NOT EXISTS (",
            "        SELECT 1 FROM listing_template lt",
            "        WHERE lt.category_marketplace_id = cm.id",
            "  );",
            "",
            "UPDATE listing_template lt",
            f"SET metadata = {_as_jsonb(_json_sql(metadata_json))},",
            "    updated_at = now()",
            "FROM category_marketplace cm",
            "JOIN categories c ON c.id = cm.category_id",
            "JOIN marketplace m ON m.id = cm.marketplace_id",
            "WHERE lt.category_marketplace_id = cm.id",
            f"  AND c.external_id = {category_id_sql}",
            f"  AND m.external_id = {marketplace_id_sql};",
            "",
            "-- ---------------------------------------------------------------------------",
            "-- 5) Insert listing_template_column fill rules",
            "-- ---------------------------------------------------------------------------",
            "INSERT INTO listing_template_column",
            "    (listing_template_id, column_index, resolve_stage, config)",
            f"SELECT lt.id, v.column_index, v.resolve_stage, {_as_jsonb('v.config')}",
            "FROM listing_template lt",
            "JOIN category_marketplace cm ON cm.id = lt.category_marketplace_id",
            "JOIN categories c ON c.id = cm.category_id",
            "JOIN marketplace m ON m.id = cm.marketplace_id",
            "CROSS JOIN (",
            "    VALUES",
        ]
    )

    value_lines = [
        f"    ({col['column_index']}, {col['resolve_stage']}, {_json_sql(col['config'])})"
        for col in columns
    ]
    lines.append(",\n".join(value_lines))
    lines.extend(
        [
            ") AS v(column_index, resolve_stage, config)",
            f"WHERE c.external_id = {category_id_sql}",
            f"  AND m.external_id = {marketplace_id_sql};",
            "",
            "COMMIT;",
            "",
        ]
    )
    return "\n".join(lines)
