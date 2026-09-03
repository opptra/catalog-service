"""Render human-run SQL for attribute_spec + listing_template metadata + columns."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from dto.listing_config import ListingTemplateMetadata
from utils.listing_template_columns import WorkbookLayout, _json_sql


def render_mapping_sql(
    *,
    columns: list[dict[str, Any]],
    attribute_spec: dict[str, list[str]],
    layout: WorkbookLayout,
    xlsm_name: str,
    mapping_name: str,
    marketplace_id: str,
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

    lines = [
        "-- Human-run only. Agent does not apply this against any database.",
        f"-- Generated from {xlsm_name} + {mapping_name} by ops.listing_mapping",
        f"-- Marketplace adapter: {marketplace_id}",
        "--",
        "-- Re-generate (from repo root, PYTHONPATH=ops:server):",
        "--   python -m listing_mapping \\",
        f"--     --marketplace {marketplace_id} \\",
        f"--     --xlsm /path/to/{xlsm_name} \\",
        f"--     --mapping /path/to/{mapping_name} \\",
        "--     --out tmp/listing_mapping/<marketplace>/sql/003_<category>_listing_mapping.sql",
        "--",
        (
            f"-- Workbook layout ({marketplace_id}): sheet={layout.sheet_name!r} "
            f"labels={layout.header_label_row} keys={layout.machine_key_row} "
            f"data={layout.data_start_row}; "
            f"valid_values={layout.valid_values_sheet!r}, "
            f"dropdown_lists={layout.dropdown_lists_sheet!r}."
        ),
        "--",
        "-- Placeholders (set before apply):",
        "--   :category_external_id     — categories.external_id (UUID)",
        "--   :marketplace_external_id  — marketplace.external_id (UUID)",
        "--   :gcs_object_key           — blank workbook GCS key if listing_template",
        "--                              row must be created (upload .xlsm first,",
        "--                              or paste the key from an existing upload)",
        "--",
        "-- Prerequisites:",
        "--   1) Category row exists (import path / UI).",
        "--   2) Marketplace row exists.",
        "--   3) Prefer uploading the blank .xlsm via the listing-template API so",
        "--      category_marketplace + listing_template already exist; then this",
        "--      script only refreshes attribute_spec, metadata, and columns.",
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
        "WHERE c.external_id = :category_external_id\n"
        "  AND m.external_id = :marketplace_external_id"
    )

    lines.extend(
        [
            "",
            "BEGIN;",
            "",
            "-- ---------------------------------------------------------------------------",
            "-- 1) Category PIM allow/mandatory list (from mapping pim_contract)",
            "-- ---------------------------------------------------------------------------",
            "UPDATE categories",
            f"SET attribute_spec = {_json_sql(attribute_spec_json)}::jsonb",
            "WHERE external_id = :category_external_id;",
            "",
            "-- ---------------------------------------------------------------------------",
            "-- 2) Ensure category × marketplace junction exists",
            "-- ---------------------------------------------------------------------------",
            "INSERT INTO category_marketplace (marketplace_id, category_id)",
            "SELECT m.id, c.id",
            "FROM marketplace m",
            "CROSS JOIN categories c",
            "WHERE m.external_id = :marketplace_external_id",
            "  AND c.external_id = :category_external_id",
            "ON CONFLICT (marketplace_id, category_id) DO NOTHING;",
            "",
            "-- ---------------------------------------------------------------------------",
            "-- 3) Delete any existing listing columns for this category × marketplace",
            "-- ---------------------------------------------------------------------------",
            "DELETE FROM listing_template_column",
            "WHERE listing_template_id IN (",
            "    SELECT lt.id",
            "    FROM listing_template lt",
            f"    {cm_from}",
            ");",
            "",
            "-- ---------------------------------------------------------------------------",
            "-- 4) Ensure listing_template row + workbook offsets (metadata)",
            "--    If the row is missing, :gcs_object_key must point at the blank .xlsm.",
            "-- ---------------------------------------------------------------------------",
            "INSERT INTO listing_template (category_marketplace_id, gcs_object_key, metadata)",
            "SELECT cm.id, :gcs_object_key, '{}'::jsonb",
            f"{cm_from}",
            "  AND NOT EXISTS (",
            "        SELECT 1 FROM listing_template lt",
            "        WHERE lt.category_marketplace_id = cm.id",
            "  );",
            "",
            "UPDATE listing_template lt",
            f"SET metadata = {_json_sql(metadata_json)}::jsonb,",
            "    updated_at = now()",
            "FROM category_marketplace cm",
            "JOIN categories c ON c.id = cm.category_id",
            "JOIN marketplace m ON m.id = cm.marketplace_id",
            "WHERE lt.category_marketplace_id = cm.id",
            "  AND c.external_id = :category_external_id",
            "  AND m.external_id = :marketplace_external_id;",
            "",
            "-- ---------------------------------------------------------------------------",
            "-- 5) Insert listing_template_column fill rules",
            "-- ---------------------------------------------------------------------------",
            "INSERT INTO listing_template_column",
            "    (listing_template_id, column_index, resolve_stage, config)",
            "SELECT lt.id, v.column_index, v.resolve_stage, v.config::jsonb",
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
            "WHERE c.external_id = :category_external_id",
            "  AND m.external_id = :marketplace_external_id;",
            "",
            "COMMIT;",
            "",
        ]
    )
    return "\n".join(lines)
