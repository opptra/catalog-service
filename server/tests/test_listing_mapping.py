"""Unit tests for ops/listing_mapping (in-memory columns + CSV text)."""

from __future__ import annotations

import pytest
from listing_mapping.csv import (
    MappingRow,
    build_attribute_spec,
    parse_mapping_csv_text,
)
from listing_mapping.overlay import overlay_columns
from listing_mapping.render import render_mapping_sql

from utils.listing_template_columns import WorkbookLayout


def _col(
    *,
    column_index: int,
    label: str,
    workbook_key: str | None = None,
    fill_type: str = "DIRECT_MAP",
    resolve_stage: int = 1,
    depends_on: int | None = None,
    valid_values: list[str] | None = None,
    valid_values_by_parent: dict[str, list[str]] | None = None,
) -> dict:
    config: dict = {
        "fill_type": fill_type,
        "label": label,
    }
    if depends_on is not None:
        config["depends_on"] = depends_on
    if valid_values is not None:
        config["valid_values"] = valid_values
    if valid_values_by_parent is not None:
        config["valid_values_by_parent"] = valid_values_by_parent
    return {
        "column_index": column_index,
        "resolve_stage": resolve_stage,
        "depends_on": depends_on,
        "workbook_key": workbook_key,
        "config": config,
    }


_SAMPLE_CSV = """Flat Field Name,Requirement,Amazon,AI_GENERATED
SKU,Mandatory,Seller SKU,false
Color,Mandatory,Color,false
Material,Optional,Material Type,true
League,Optional,League Name,true
Team,Optional,,false
Extra Note,Optional,Notes,false
"""


def test_parse_mapping_csv_text() -> None:
    mapping = parse_mapping_csv_text(_SAMPLE_CSV)
    assert mapping.marketplace_header == "Amazon"
    assert len(mapping.rows) == 6
    sku = mapping.rows[0]
    assert sku.flat_field_name == "SKU"
    assert sku.mandatory is True
    assert sku.marketplace_column == "Seller SKU"
    assert sku.ai_generated is False
    league = next(r for r in mapping.rows if r.flat_field_name == "League")
    assert league.ai_generated is True
    assert league.marketplace_column == "League Name"
    team = next(r for r in mapping.rows if r.flat_field_name == "Team")
    assert team.marketplace_column is None


def test_build_attribute_spec_injects_sku() -> None:
    rows = [
        MappingRow("Color", True, "Color", False),
        MappingRow("Material", False, "Material", True),
    ]
    spec = build_attribute_spec(rows)
    assert spec["allowed"][0] == "SKU"
    assert "SKU" in spec["mandatory"]
    assert "Color" in spec["mandatory"]
    assert "Material" in spec["allowed"]
    assert "Material" not in spec["mandatory"]


def test_overlay_fill_types() -> None:
    workbook = [
        _col(column_index=1, label="Seller SKU", workbook_key="item_sku"),
        _col(
            column_index=2,
            label="Color",
            workbook_key="color_name",
            fill_type="ENUM",
            valid_values=["Black", "White"],
        ),
        _col(column_index=3, label="Material Type", workbook_key="material_type"),
        _col(
            column_index=4,
            label="League Name",
            workbook_key="league_name",
            fill_type="ENUM",
            valid_values=["NFL", "NBA"],
        ),
        _col(
            column_index=5,
            label="Team Name",
            workbook_key="team_name",
            fill_type="ENUM",
            resolve_stage=2,
            depends_on=4,
            valid_values_by_parent={"NFL": ["Patriots"], "NBA": ["Lakers"]},
        ),
        _col(column_index=6, label="Notes", workbook_key="notes"),
        _col(column_index=7, label="Product ID", workbook_key="external_product_id"),
    ]
    mapping = parse_mapping_csv_text(_SAMPLE_CSV)
    result = overlay_columns(workbook, mapping)
    by_index = {c["column_index"]: c["config"] for c in result.columns}

    assert by_index[1]["fill_type"] == "DIRECT_MAP"
    assert by_index[1]["source"] == {"from": "SKU_MASTER", "key": "SKU"}
    assert "requiredness" not in by_index[1]
    assert "machine_key" not in by_index[1]

    assert by_index[2]["fill_type"] == "ENUM"
    assert by_index[2]["valid_values"] == ["Black", "White"]
    assert by_index[2]["source"] == {"from": "SKU_MASTER", "key": "Color"}

    assert by_index[3]["fill_type"] == "AI_TEXT"
    assert "source" not in by_index[3]

    assert by_index[4]["fill_type"] == "ENUM"
    assert "source" not in by_index[4]
    assert by_index[4]["valid_values"] == ["NFL", "NBA"]

    assert by_index[6]["fill_type"] == "DIRECT_MAP"
    assert by_index[6]["source"]["key"] == "Extra Note"

    assert by_index[7]["fill_type"] == "SKIP"
    assert "valid_values" not in by_index[7]

    assert by_index[5]["fill_type"] == "SKIP"
    assert result.warnings == []

    assert "SKU" in result.attribute_spec["mandatory"]
    assert "Color" in result.attribute_spec["mandatory"]
    assert "Team" in result.attribute_spec["allowed"]
    assert "Team" not in result.attribute_spec["mandatory"]


def test_overlay_warns_when_enum_depends_on_skip_parent() -> None:
    workbook = [
        _col(
            column_index=1,
            label="League Name",
            workbook_key="league_name",
            fill_type="ENUM",
            valid_values=["NFL"],
        ),
        _col(
            column_index=2,
            label="Team Name",
            workbook_key="team_name",
            fill_type="ENUM",
            resolve_stage=2,
            depends_on=1,
            valid_values_by_parent={"NFL": ["Patriots"]},
        ),
    ]
    mapping = parse_mapping_csv_text(
        "Flat Field Name,Requirement,Amazon,AI_GENERATED\nTeam,Optional,Team Name,true\n"
    )
    result = overlay_columns(workbook, mapping)
    by_index = {c["column_index"]: c["config"] for c in result.columns}
    assert by_index[1]["fill_type"] == "SKIP"
    assert by_index[2]["fill_type"] == "ENUM"
    assert by_index[2]["depends_on"] == 1
    assert "source" not in by_index[2]
    assert "machine_key" not in by_index[2]
    assert any("depends_on" in w and "SKIP" in w for w in result.warnings)


def test_overlay_match_by_workbook_key() -> None:
    workbook = [_col(column_index=1, label="Seller SKU", workbook_key="item_sku")]
    mapping = parse_mapping_csv_text(
        "Flat Field Name,Requirement,Amazon,AI_GENERATED\nSKU,Mandatory,item_sku,false\n"
    )
    result = overlay_columns(workbook, mapping)
    assert result.columns[0]["config"]["fill_type"] == "DIRECT_MAP"
    assert "machine_key" not in result.columns[0]["config"]


def test_overlay_unmatched_marketplace_name_fails() -> None:
    workbook = [_col(column_index=1, label="Seller SKU", workbook_key="item_sku")]
    mapping = parse_mapping_csv_text(
        "Flat Field Name,Requirement,Amazon,AI_GENERATED\nSKU,Mandatory,Not A Column,false\n"
    )
    with pytest.raises(ValueError, match="matches no workbook column"):
        overlay_columns(workbook, mapping)


def test_overlay_duplicate_marketplace_in_csv_fails() -> None:
    with pytest.raises(ValueError, match="already mapped"):
        parse_mapping_csv_text(
            "Flat Field Name,Requirement,Amazon,AI_GENERATED\n"
            "SKU,Mandatory,Seller SKU,false\n"
            "Color,Mandatory,Seller SKU,false\n"
        )


def test_render_mapping_sql_contains_three_updates() -> None:
    workbook = [
        _col(column_index=1, label="Seller SKU", workbook_key="item_sku"),
        _col(
            column_index=2,
            label="Color",
            workbook_key="color_name",
            fill_type="ENUM",
            valid_values=["Black"],
        ),
    ]
    mapping = parse_mapping_csv_text(
        "Flat Field Name,Requirement,Amazon,AI_GENERATED\n"
        "SKU,Mandatory,Seller SKU,false\n"
        "Color,Mandatory,Color,false\n"
    )
    result = overlay_columns(workbook, mapping)
    sql = render_mapping_sql(
        columns=result.columns,
        attribute_spec=result.attribute_spec,
        layout=WorkbookLayout(
            sheet_name="Template",
            header_label_row=4,
            machine_key_row=5,
            data_start_row=7,
        ),
        xlsm_name="cat.xlsm",
        csv_name="map.csv",
        marketplace_header="Amazon",
        warnings=result.warnings,
    )
    assert "UPDATE categories" in sql
    assert "attribute_spec" in sql
    assert ":category_external_id" in sql
    assert ":marketplace_external_id" in sql
    assert ":gcs_object_key" in sql
    assert "INSERT INTO category_marketplace" in sql
    assert "DELETE FROM listing_template_column" in sql
    assert "INSERT INTO listing_template" in sql
    assert "UPDATE listing_template" in sql
    assert "SET metadata" in sql
    assert "INSERT INTO listing_template_column" in sql
    assert ":cm_id" not in sql
    assert '"requiredness"' not in sql
    assert '"machine_key"' not in sql
    assert "sheet_name" in sql
    assert "header_label_row" in sql
