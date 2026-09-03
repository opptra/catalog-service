"""Unit tests for ops/listing_mapping (mapping workbook + overlay + Amazon adapter)."""

from __future__ import annotations

from pathlib import Path

import pytest
from listing_mapping.mapping_workbook import (
    FillMode,
    ListingMapRow,
    MappingWorkbook,
    PimFieldRow,
    build_attribute_spec,
    parse_mapping_workbook,
)
from listing_mapping.marketplace import MarketplaceId, parse_marketplace_id
from listing_mapping.marketplace.registry import get_adapter
from listing_mapping.overlay import overlay_columns
from listing_mapping.render import render_mapping_sql
from openpyxl import Workbook

from utils.listing_template_columns import WorkbookLayout

_REPO = Path(__file__).resolve().parents[2]
_TEMPLATE = _REPO / "tmp" / "listing_mapping_template.xlsx"


def _col(
    *,
    column_index: int,
    label: str,
    fill_type: str = "DIRECT_MAP",
    resolve_stage: int = 1,
    depends_on: int | None = None,
    valid_values: list[str] | None = None,
    valid_values_by_parent: dict[str, list[str]] | None = None,
) -> dict:
    config: dict = {"fill_type": fill_type, "label": label}
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
        "workbook_key": None,
        "config": config,
    }


def test_parse_marketplace_id() -> None:
    assert parse_marketplace_id("amazon") is MarketplaceId.AMAZON
    assert parse_marketplace_id("AMAZON") is MarketplaceId.AMAZON
    with pytest.raises(ValueError, match="Unknown marketplace"):
        parse_marketplace_id("SHOPIFY")


def test_amazon_adapter_default_layout() -> None:
    layout = get_adapter(MarketplaceId.AMAZON).workbook_layout()
    assert layout.sheet_name == "Template"
    assert layout.header_label_row == 4
    assert layout.machine_key_row == 5
    assert layout.data_start_row == 7
    assert layout.valid_values_sheet == "Valid Values"


def test_amazon_adapter_overrides() -> None:
    layout = get_adapter(MarketplaceId.AMAZON).workbook_layout(
        sheet_name="Custom",
        data_start_row=9,
    )
    assert layout.sheet_name == "Custom"
    assert layout.data_start_row == 9
    assert layout.header_label_row == 4


def test_flipkart_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="FLIPKART"):
        get_adapter(MarketplaceId.FLIPKART).workbook_layout()


def test_build_attribute_spec_injects_sku() -> None:
    spec = build_attribute_spec(
        [
            PimFieldRow("Color", True),
            PimFieldRow("Material", False),
        ]
    )
    assert spec["allowed"][0] == "SKU"
    assert "SKU" in spec["mandatory"]
    assert "Color" in spec["mandatory"]


def test_overlay_by_column_index_fill_modes() -> None:
    workbook = [
        _col(column_index=1, label="Seller SKU"),
        _col(
            column_index=2,
            label="Color",
            fill_type="ENUM",
            valid_values=["Black", "White"],
        ),
        _col(
            column_index=3,
            label="League",
            fill_type="ENUM",
            valid_values=["NFL"],
        ),
        _col(column_index=4, label="Item Name"),
        _col(column_index=5, label="Main Image"),
        _col(column_index=6, label="Notes"),
        _col(column_index=7, label="Unused"),
    ]
    mapping = MappingWorkbook(
        pim_fields=[
            PimFieldRow("SKU", True),
            PimFieldRow("Color", True),
        ],
        listing_rows=[
            ListingMapRow(1, FillMode.COPY_PIM, "SKU", None, None),
            ListingMapRow(2, FillMode.ENUM_FROM_PIM, "Color", None, None),
            ListingMapRow(3, FillMode.ENUM_AI, None, None, None),
            ListingMapRow(4, FillMode.COPY_GENERATION, None, "TITLE", None),
            ListingMapRow(5, FillMode.IMAGE, None, "IMAGE:1", None),
            ListingMapRow(6, FillMode.AI_TEXT, None, None, None),
        ],
    )
    result = overlay_columns(workbook, mapping)
    by_index = {c["column_index"]: c["config"] for c in result.columns}

    assert by_index[1]["fill_type"] == "DIRECT_MAP"
    assert by_index[1]["source"] == {"from": "SKU_MASTER", "key": "SKU"}
    assert by_index[2]["fill_type"] == "ENUM"
    assert by_index[2]["source"]["key"] == "Color"
    assert by_index[3]["fill_type"] == "ENUM"
    assert "source" not in by_index[3]
    assert by_index[4]["fill_type"] == "DIRECT_MAP"
    assert by_index[4]["source"]["attribute_name"] == "TITLE"
    assert by_index[5]["fill_type"] == "IMAGE"
    assert by_index[5]["source"]["slot"] == 1
    assert by_index[6]["fill_type"] == "AI_TEXT"
    assert by_index[7]["fill_type"] == "SKIP"
    assert "requiredness" not in by_index[1]
    assert "machine_key" not in by_index[1]


def test_overlay_unknown_column_index_fails() -> None:
    workbook = [_col(column_index=1, label="Seller SKU")]
    mapping = MappingWorkbook(
        pim_fields=[PimFieldRow("SKU", True)],
        listing_rows=[ListingMapRow(99, FillMode.COPY_PIM, "SKU", None, None)],
    )
    with pytest.raises(ValueError, match="not found in workbook"):
        overlay_columns(workbook, mapping)


def test_render_mapping_sql() -> None:
    workbook = [_col(column_index=1, label="Seller SKU")]
    mapping = MappingWorkbook(
        pim_fields=[PimFieldRow("SKU", True)],
        listing_rows=[ListingMapRow(1, FillMode.COPY_PIM, "SKU", None, None)],
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
        mapping_name="map.xlsx",
        marketplace_id="AMAZON",
    )
    assert "UPDATE categories" in sql
    assert "--marketplace AMAZON" in sql
    assert ":category_external_id" in sql
    assert "INSERT INTO listing_template_column" in sql


@pytest.mark.skipif(not _TEMPLATE.is_file(), reason="tmp listing_mapping_template.xlsx missing")
def test_parse_tmp_mapping_template() -> None:
    mapping = parse_mapping_workbook(_TEMPLATE)
    assert mapping.pim_fields
    assert mapping.listing_rows
    assert any(r.pim_field == "SKU" for r in mapping.pim_fields)
    assert any(r.fill_mode == FillMode.COPY_PIM for r in mapping.listing_rows)


def test_parse_mapping_workbook_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "map.xlsx"
    wb = Workbook()
    ws_pim = wb.active
    ws_pim.title = "pim_contract"
    ws_pim.append(["pim_field", "requirement"])
    ws_pim.append(["SKU", "Mandatory"])
    ws_pim.append(["Color", "Optional"])
    ws_map = wb.create_sheet("listing_map")
    ws_map.append(
        [
            "column_index",
            "marketplace_column",
            "fill_mode",
            "pim_field",
            "generation",
            "constant_value",
            "status",
        ]
    )
    ws_map.append([1, "Seller SKU", "COPY_PIM", "SKU", "", "", "OK"])
    ws_map.append([2, "Color", "ENUM_FROM_PIM", "Color", "", "", "OK"])
    wb.save(path)
    mapping = parse_mapping_workbook(path)
    assert len(mapping.pim_fields) == 2
    assert mapping.listing_rows[0].column_index == 1
    assert mapping.listing_rows[1].fill_mode == FillMode.ENUM_FROM_PIM
