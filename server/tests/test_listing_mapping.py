"""Unit tests for ops/listing_mapping (mapping workbook + overlay + Amazon adapter)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from listing_mapping.__main__ import collect_apply_ids, jobs_from_args
from listing_mapping.build_template import (
    PIM_ROWS,
    _pim_contract_status_formula,
    _status_formula,
)
from listing_mapping.mapping_workbook import (
    FillMode,
    ListingMapRow,
    MappingWorkbook,
    MarketplaceColumnRow,
    PimFieldRow,
    build_attribute_spec,
    parse_mapping_workbook,
)
from listing_mapping.marketplace import MarketplaceId, parse_marketplace_id
from listing_mapping.marketplace.registry import get_adapter
from listing_mapping.overlay import overlay_columns
from listing_mapping.render import ApplyIds, render_mapping_sql
from openpyxl import Workbook
from openpyxl.worksheet.datavalidation import DataValidation

from utils.listing_template_columns import WorkbookLayout, build_columns

_REPO = Path(__file__).resolve().parents[2]
_MAP = _REPO / "ops" / "docs" / "listing_mapping_template.xlsx"


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


def _mapping(
    listing_rows: list[ListingMapRow],
    *,
    pim_fields: list[PimFieldRow] | None = None,
) -> MappingWorkbook:
    return MappingWorkbook(
        pim_fields=pim_fields
        or [
            PimFieldRow("SKU", True),
            PimFieldRow("Color", True),
        ],
        marketplace_columns=[
            MarketplaceColumnRow(
                excel_row=2 + i,
                column_index=row.column_index,
                marketplace_column=f"col-{row.column_index}",
            )
            for i, row in enumerate(listing_rows)
        ],
        listing_rows=listing_rows,
    )


def _write_mapping(
    path: Path,
    *,
    rows: list[tuple[int, str, str, str, str, str]],
    pim: list[tuple[str, str]] | None = None,
    sheet: str = "amazon_mapping",
) -> None:
    wb = Workbook()
    ws_pim = wb.active
    ws_pim.title = "pim_contract"
    ws_pim.append(["pim_field", "requirement"])
    for field, req in pim or [("SKU", "Mandatory"), ("Color", "Optional")]:
        ws_pim.append([field, req])
    ws_map = wb.create_sheet(sheet)
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
    for row in rows:
        ws_map.append([*row, "OK"])
    wb.save(path)


def test_jobs_from_args_all_at_once(tmp_path: Path) -> None:
    args = argparse.Namespace(
        marketplace=None,
        xlsm=None,
        out=None,
        out_dir=tmp_path / "sql",
        amazon_xlsm=tmp_path / "amazon.xlsm",
        flipkart_xlsm=tmp_path / "flipkart.xlsm",
        myntra_xlsm=tmp_path / "myntra.xlsx",
        amazon_sheet_name="Template",
        flipkart_sheet_name="bedsheet",
        myntra_sheet_name="Bedsheets",
        sheet_name=None,
        header_label_row=None,
        machine_key_row=None,
        data_start_row=None,
        only=None,
    )
    jobs = jobs_from_args(args)
    assert [job.marketplace_id for job in jobs] == [
        MarketplaceId.AMAZON,
        MarketplaceId.FLIPKART,
        MarketplaceId.MYNTRA,
    ]
    assert jobs[0].out.name == "amazon_listing_mapping.sql"
    assert jobs[1].sheet_name == "bedsheet"
    assert jobs[2].sheet_name == "Bedsheets"


def test_jobs_from_args_rejects_mixed_modes(tmp_path: Path) -> None:
    args = argparse.Namespace(
        marketplace="AMAZON",
        xlsm=tmp_path / "amazon.xlsm",
        out=tmp_path / "out.sql",
        out_dir=tmp_path / "sql",
        amazon_xlsm=tmp_path / "amazon.xlsm",
        flipkart_xlsm=None,
        myntra_xlsm=None,
        amazon_sheet_name=None,
        flipkart_sheet_name=None,
        myntra_sheet_name=None,
        sheet_name=None,
        header_label_row=None,
        machine_key_row=None,
        data_start_row=None,
        only=None,
    )
    with pytest.raises(ValueError, match="not both"):
        jobs_from_args(args)
    assert parse_marketplace_id("amazon") is MarketplaceId.AMAZON
    assert parse_marketplace_id("AMAZON") is MarketplaceId.AMAZON
    with pytest.raises(ValueError, match="Unknown marketplace"):
        parse_marketplace_id("SHOPIFY")


def test_jobs_from_args_only_amazon_keeps_other_files(tmp_path: Path) -> None:
    args = argparse.Namespace(
        marketplace=None,
        xlsm=None,
        out=None,
        out_dir=tmp_path / "sql",
        amazon_xlsm=tmp_path / "amazon.xlsm",
        flipkart_xlsm=tmp_path / "flipkart.xlsm",
        myntra_xlsm=tmp_path / "myntra.xlsx",
        amazon_sheet_name=None,
        flipkart_sheet_name=None,
        myntra_sheet_name=None,
        sheet_name=None,
        header_label_row=None,
        machine_key_row=None,
        data_start_row=None,
        only="AMAZON",
    )
    jobs = jobs_from_args(args)
    assert [job.marketplace_id for job in jobs] == [MarketplaceId.AMAZON]


def test_jobs_from_args_amazon_file_only(tmp_path: Path) -> None:
    args = argparse.Namespace(
        marketplace=None,
        xlsm=None,
        out=None,
        out_dir=tmp_path / "sql",
        amazon_xlsm=tmp_path / "amazon.xlsm",
        flipkart_xlsm=None,
        myntra_xlsm=None,
        amazon_sheet_name=None,
        flipkart_sheet_name=None,
        myntra_sheet_name=None,
        sheet_name=None,
        header_label_row=None,
        machine_key_row=None,
        data_start_row=None,
        only=None,
    )
    jobs = jobs_from_args(args)
    assert [job.marketplace_id for job in jobs] == [MarketplaceId.AMAZON]


def test_jobs_from_args_only_without_matching_file(tmp_path: Path) -> None:
    args = argparse.Namespace(
        marketplace=None,
        xlsm=None,
        out=None,
        out_dir=tmp_path / "sql",
        amazon_xlsm=tmp_path / "amazon.xlsm",
        flipkart_xlsm=None,
        myntra_xlsm=None,
        amazon_sheet_name=None,
        flipkart_sheet_name=None,
        myntra_sheet_name=None,
        sheet_name=None,
        header_label_row=None,
        machine_key_row=None,
        data_start_row=None,
        only="FLIPKART",
    )
    with pytest.raises(ValueError, match="FLIPKART"):
        jobs_from_args(args)


def test_collect_apply_ids_from_flags_only_selected_jobs(tmp_path: Path) -> None:
    args = argparse.Namespace(
        marketplace=None,
        xlsm=None,
        out=None,
        out_dir=tmp_path / "sql",
        amazon_xlsm=tmp_path / "amazon.xlsm",
        flipkart_xlsm=tmp_path / "flipkart.xlsm",
        myntra_xlsm=tmp_path / "myntra.xlsx",
        amazon_sheet_name=None,
        flipkart_sheet_name=None,
        myntra_sheet_name=None,
        sheet_name=None,
        header_label_row=None,
        machine_key_row=None,
        data_start_row=None,
        only="AMAZON",
        category_external_id="1c6b0000-0000-4000-8000-000000000001",
        marketplace_external_id=None,
        gcs_object_key=None,
        amazon_marketplace_external_id="1c6b0000-0000-4000-8000-0000000000aa",
        flipkart_marketplace_external_id="1c6b0000-0000-4000-8000-0000000000ff",
        myntra_marketplace_external_id="1c6b0000-0000-4000-8000-0000000000bb",
        amazon_gcs_object_key="listing-templates/amazon.xlsm",
        flipkart_gcs_object_key="listing-templates/flipkart.xlsm",
        myntra_gcs_object_key="listing-templates/myntra.xlsx",
    )
    jobs = jobs_from_args(args)
    selected = collect_apply_ids(args, jobs, prompt=lambda _label: pytest.fail("prompted"))
    assert len(selected) == 1
    job, ids = selected[0]
    assert job.marketplace_id is MarketplaceId.AMAZON
    assert ids.category_external_id == "1c6b0000-0000-4000-8000-000000000001"
    assert ids.marketplace_external_id == "1c6b0000-0000-4000-8000-0000000000aa"
    assert ids.gcs_object_key == "listing-templates/amazon.xlsm"


def test_collect_apply_ids_blank_skips_extra_marketplace(tmp_path: Path) -> None:
    args = argparse.Namespace(
        marketplace=None,
        xlsm=None,
        out=None,
        out_dir=tmp_path / "sql",
        amazon_xlsm=tmp_path / "amazon.xlsm",
        flipkart_xlsm=tmp_path / "flipkart.xlsm",
        myntra_xlsm=tmp_path / "myntra.xlsx",
        amazon_sheet_name=None,
        flipkart_sheet_name=None,
        myntra_sheet_name=None,
        sheet_name=None,
        header_label_row=None,
        machine_key_row=None,
        data_start_row=None,
        only=None,
        category_external_id=None,
        marketplace_external_id=None,
        gcs_object_key=None,
        amazon_marketplace_external_id=None,
        flipkart_marketplace_external_id=None,
        myntra_marketplace_external_id=None,
        amazon_gcs_object_key=None,
        flipkart_gcs_object_key=None,
        myntra_gcs_object_key=None,
    )
    jobs = jobs_from_args(args)
    answers = {
        "category.external_id (UUID)": "1c6b0000-0000-4000-8000-000000000001",
        "AMAZON marketplace.external_id (UUID, Enter to skip)": (
            "1c6b0000-0000-4000-8000-0000000000aa"
        ),
        "AMAZON gcs_object_key (blank if listing_template already exists)": "",
        "FLIPKART marketplace.external_id (UUID, Enter to skip)": "",
        "MYNTRA marketplace.external_id (UUID, Enter to skip)": "",
    }
    selected = collect_apply_ids(args, jobs, prompt=lambda label: answers[label])
    assert [job.marketplace_id for job, _ids in selected] == [MarketplaceId.AMAZON]
    assert selected[0][1].gcs_object_key == ""


def test_amazon_adapter_default_layout() -> None:
    layout = get_adapter(MarketplaceId.AMAZON).workbook_layout()
    assert layout.sheet_name == "Template"
    assert layout.header_label_row == 4
    assert layout.machine_key_row == 5
    assert layout.data_start_row == 7
    assert layout.valid_values_sheet == "Valid Values"
    assert layout.enum_discovery == "amazon"


def test_amazon_adapter_overrides() -> None:
    layout = get_adapter(MarketplaceId.AMAZON).workbook_layout(
        sheet_name="Custom",
        data_start_row=9,
    )
    assert layout.sheet_name == "Custom"
    assert layout.data_start_row == 9
    assert layout.header_label_row == 4


def test_flipkart_adapter_default_layout() -> None:
    layout = get_adapter(MarketplaceId.FLIPKART).workbook_layout()
    assert layout.sheet_name == "bedsheet"
    assert layout.header_label_row == 1
    assert layout.machine_key_row == 2
    assert layout.data_start_row == 5
    assert layout.valid_values_sheet is None
    assert layout.enum_discovery == "flipkart"


def test_myntra_adapter_default_layout() -> None:
    layout = get_adapter(MarketplaceId.MYNTRA).workbook_layout()
    assert layout.sheet_name == "Bedsheets"
    assert layout.header_label_row == 3
    assert layout.machine_key_row == 3
    assert layout.data_start_row == 4
    assert layout.valid_values_sheet is None
    assert layout.enum_discovery == "myntra"


def test_myntra_adapter_overrides() -> None:
    layout = get_adapter(MarketplaceId.MYNTRA).workbook_layout(sheet_name="Curtains")
    assert layout.sheet_name == "Curtains"
    assert layout.data_start_row == 4


def test_flipkart_adapter_overrides() -> None:
    layout = get_adapter(MarketplaceId.FLIPKART).workbook_layout(sheet_name="curtain")
    assert layout.sheet_name == "curtain"
    assert layout.data_start_row == 5


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
    mapping = _mapping(
        [
            ListingMapRow(1, FillMode.COPY_PIM, "SKU", None, None),
            ListingMapRow(2, FillMode.ENUM_FROM_PIM, "Color", None, None),
            ListingMapRow(3, FillMode.ENUM_AI, None, None, None),
            ListingMapRow(4, FillMode.COPY_GENERATION, None, "TITLE", None),
            ListingMapRow(5, FillMode.IMAGE, None, "IMAGE", None),
            ListingMapRow(6, FillMode.AI_TEXT, None, None, None),
            ListingMapRow(7, FillMode.SKIP, None, None, None),
        ]
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
    assert "source" not in by_index[6]
    assert by_index[7]["fill_type"] == "SKIP"
    assert "requiredness" not in by_index[1]
    assert "machine_key" not in by_index[1]


def test_overlay_enum_and_ai_text_optional_pim() -> None:
    workbook = [
        _col(
            column_index=1,
            label="Color",
            fill_type="ENUM",
            valid_values=["Black", "White"],
        ),
        _col(
            column_index=2,
            label="League",
            fill_type="ENUM",
            valid_values=["NFL"],
        ),
        _col(column_index=3, label="Notes"),
        _col(column_index=4, label="Fabric Type"),
    ]
    mapping = _mapping(
        [
            ListingMapRow(1, FillMode.ENUM, "Color", None, None),
            ListingMapRow(2, FillMode.ENUM, None, None, None),
            ListingMapRow(3, FillMode.AI_TEXT, None, None, None),
            ListingMapRow(4, FillMode.AI_TEXT, "Color", None, None),
        ]
    )
    result = overlay_columns(workbook, mapping)
    by_index = {c["column_index"]: c["config"] for c in result.columns}
    assert by_index[1]["fill_type"] == "ENUM"
    assert by_index[1]["source"] == {"from": "SKU_MASTER", "key": "Color"}
    assert by_index[2]["fill_type"] == "ENUM"
    assert "source" not in by_index[2]
    assert by_index[3]["fill_type"] == "AI_TEXT"
    assert "source" not in by_index[3]
    assert by_index[4]["fill_type"] == "AI_TEXT"
    assert by_index[4]["source"] == {"from": "SKU_MASTER", "key": "Color"}


def test_overlay_enum_on_non_dropdown_fails() -> None:
    workbook = [_col(column_index=1, label="Notes")]
    mapping = _mapping([ListingMapRow(1, FillMode.ENUM, None, None, None)])
    with pytest.raises(ValueError, match="no dropdown"):
        overlay_columns(workbook, mapping)


def test_overlay_ai_text_on_dropdown_fails() -> None:
    workbook = [
        _col(
            column_index=1,
            label="Color",
            fill_type="ENUM",
            valid_values=["Black"],
        )
    ]
    mapping = _mapping([ListingMapRow(1, FillMode.AI_TEXT, None, None, None)])
    with pytest.raises(ValueError, match="is a dropdown"):
        overlay_columns(workbook, mapping)


def test_overlay_repeats_generation_name_by_column_order() -> None:
    workbook = [
        _col(column_index=1, label="Highlight A"),
        _col(column_index=2, label="Highlight B"),
        _col(column_index=3, label="Bullet A"),
        _col(column_index=4, label="Bullet B"),
        _col(column_index=5, label="Image A"),
        _col(column_index=6, label="Image B"),
    ]
    mapping = _mapping(
        [
            ListingMapRow(1, FillMode.COPY_GENERATION, None, "ITEM_HIGHLIGHTS", None),
            ListingMapRow(2, FillMode.COPY_GENERATION, None, "ITEM_HIGHLIGHTS", None),
            ListingMapRow(3, FillMode.COPY_GENERATION, None, "BULLET_POINTS", None),
            ListingMapRow(4, FillMode.COPY_GENERATION, None, "BULLET_POINTS", None),
            ListingMapRow(5, FillMode.IMAGE, None, "IMAGE", None),
            ListingMapRow(6, FillMode.IMAGE, None, "IMAGE", None),
        ]
    )
    result = overlay_columns(workbook, mapping)
    by_index = {c["column_index"]: c["config"]["source"] for c in result.columns}
    assert by_index[1]["attribute_name"] == "ITEM_HIGHLIGHTS"
    assert by_index[1]["index"] == 1
    assert by_index[2]["index"] == 2
    assert by_index[3]["attribute_name"] == "BULLET_POINTS"
    assert by_index[3]["index"] == 1
    assert by_index[4]["index"] == 2
    assert by_index[5]["attribute_name"] == "IMAGE"
    assert by_index[5]["slot"] == 1
    assert by_index[6]["slot"] == 2


def test_overlay_missing_column_index_fails() -> None:
    workbook = [
        _col(column_index=1, label="Seller SKU"),
        _col(column_index=2, label="Color"),
    ]
    mapping = _mapping(
        [ListingMapRow(1, FillMode.COPY_PIM, "SKU", None, None)],
        pim_fields=[PimFieldRow("SKU", True)],
    )
    with pytest.raises(ValueError, match="no silent SKIP"):
        overlay_columns(workbook, mapping)


def test_overlay_unknown_column_index_fails() -> None:
    workbook = [_col(column_index=1, label="Seller SKU")]
    mapping = _mapping(
        [ListingMapRow(99, FillMode.COPY_PIM, "SKU", None, None)],
        pim_fields=[PimFieldRow("SKU", True)],
    )
    with pytest.raises(ValueError, match="not found in workbook"):
        overlay_columns(workbook, mapping)


def test_overlay_skip_blank_workbook_column() -> None:
    workbook = [
        _col(column_index=1, label="Seller SKU"),
        _col(column_index=3, label="Listing Status"),
    ]
    mapping = _mapping(
        [
            ListingMapRow(1, FillMode.COPY_PIM, "SKU", None, None),
            ListingMapRow(2, FillMode.SKIP, None, None, None),
            ListingMapRow(3, FillMode.CONSTANT, None, None, "ACTIVE"),
        ],
        pim_fields=[PimFieldRow("SKU", True)],
    )
    result = overlay_columns(workbook, mapping)
    assert [c["column_index"] for c in result.columns] == [1, 3]
    assert result.columns[1]["config"]["fill_type"] == "CONSTANT"


def test_render_mapping_sql() -> None:
    workbook = [_col(column_index=1, label="Seller SKU")]
    mapping = _mapping(
        [ListingMapRow(1, FillMode.COPY_PIM, "SKU", None, None)],
        pim_fields=[PimFieldRow("SKU", True)],
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
            enum_discovery="amazon",
        ),
        xlsm_name="cat.xlsm",
        mapping_name="map.xlsx",
        marketplace_id="AMAZON",
        apply_ids=ApplyIds(
            category_external_id="1c6b0000-0000-4000-8000-000000000001",
            marketplace_external_id="1c6b0000-0000-4000-8000-000000000002",
            gcs_object_key="listing-templates/amazon.xlsm",
        ),
    )
    assert "UPDATE categories" in sql
    assert "jsonb_array_elements" in sql
    assert "Does not replace or drop existing entries" in sql
    assert "SET attribute_spec = '{" not in sql
    assert "--marketplace AMAZON" in sql
    assert "CAST('1c6b0000-0000-4000-8000-000000000001' AS uuid)" in sql
    assert "CAST('1c6b0000-0000-4000-8000-000000000002' AS uuid)" in sql
    assert "CAST('listing-templates/amazon.xlsm' AS text)" in sql
    assert ":category_external_id" not in sql
    assert "--category-external-id 1c6b0000-0000-4000-8000-000000000001" in sql
    assert "INSERT INTO listing_template_column" in sql
    assert "FROM listing_template lt\n    FROM " not in sql
    assert (
        "FROM listing_template lt\n"
        "    JOIN category_marketplace cm ON cm.id = lt.category_marketplace_id"
    ) in sql
    assert "::jsonb" not in sql
    assert "CAST(" in sql
    assert "AS jsonb)" in sql


@pytest.mark.skipif(not _MAP.is_file(), reason="listing mapping template xlsx missing")
def test_parse_tmp_mapping_template_examples() -> None:
    amazon = parse_mapping_workbook(_MAP, MarketplaceId.AMAZON)
    flipkart = parse_mapping_workbook(_MAP, MarketplaceId.FLIPKART)
    myntra = parse_mapping_workbook(_MAP, MarketplaceId.MYNTRA)
    assert any(r.pim_field == "SKU" for r in amazon.pim_fields)
    for mapping in (amazon, flipkart, myntra):
        assert mapping.listing_rows
        assert len(mapping.marketplace_columns) == len(mapping.listing_rows)
        modes = {row.fill_mode for row in mapping.listing_rows}
        assert FillMode.COPY_PIM in modes
        assert FillMode.ENUM in modes
        assert FillMode.AI_TEXT in modes
        assert FillMode.IMAGE in modes
        assert FillMode.SKIP in modes
        enum_rows = [r for r in mapping.listing_rows if r.fill_mode == FillMode.ENUM]
        assert any(r.pim_field for r in enum_rows)
        assert any(not r.pim_field for r in enum_rows)
        ai_rows = [r for r in mapping.listing_rows if r.fill_mode == FillMode.AI_TEXT]
        assert any(r.pim_field for r in ai_rows)
        assert any(not r.pim_field for r in ai_rows)


def test_status_formula_looks_through_pim_rows_and_names_the_failure() -> None:
    assert PIM_ROWS == 1000
    formula = _status_formula(2, gen_last=9, map_last_row=320)
    assert f"$A${PIM_ROWS}" in formula
    assert "ERROR: pim_field is not on pim_contract" in formula
    assert "ERROR: generation must be blank for ENUM" in formula
    assert "ERROR: pim_contract requirement required for this pim_field" in formula
    pim_status = _pim_contract_status_formula(81)
    assert "ERROR: requirement required" in pim_status
    assert f"$A${PIM_ROWS}" in pim_status


def test_parse_pim_contract_requires_requirement(tmp_path: Path) -> None:
    path = tmp_path / "map.xlsx"
    _write_mapping(
        path,
        rows=[(1, "Seller SKU", "COPY_PIM", "SKU", "", "")],
        pim=[("SKU", "Mandatory"), ("Pattern", "")],
    )
    with pytest.raises(ValueError, match="pim_contract row 3: requirement required"):
        parse_mapping_workbook(path, MarketplaceId.AMAZON)


def test_parse_mapping_workbook_requires_fill_mode_for_each_marketplace_column(
    tmp_path: Path,
) -> None:
    path = tmp_path / "map.xlsx"
    _write_mapping(
        path,
        rows=[
            (1, "Seller SKU", "COPY_PIM", "SKU", "", ""),
            (2, "Color", "", "", "", ""),
        ],
    )
    with pytest.raises(ValueError, match="fill_mode required"):
        parse_mapping_workbook(path, MarketplaceId.AMAZON)


def test_parse_mapping_workbook_occupancy_errors_cite_sheet(tmp_path: Path) -> None:
    path = tmp_path / "map.xlsx"
    _write_mapping(
        path,
        rows=[(1, "Seller SKU", "COPY_PIM", "", "", "")],
    )
    with pytest.raises(ValueError, match="amazon_mapping.*COPY_PIM requires pim_field"):
        parse_mapping_workbook(path, MarketplaceId.AMAZON)


def test_parse_mapping_workbook_rejects_generation_ordinal(tmp_path: Path) -> None:
    path = tmp_path / "map.xlsx"
    _write_mapping(
        path,
        rows=[(1, "Bullet", "COPY_GENERATION", "", "BULLET_POINTS:1", "")],
    )
    with pytest.raises(ValueError, match="bare name"):
        parse_mapping_workbook(path, MarketplaceId.AMAZON)


def test_parse_mapping_workbook_enum_and_aliases(tmp_path: Path) -> None:
    path = tmp_path / "map.xlsx"
    _write_mapping(
        path,
        rows=[
            (1, "Seller SKU", "COPY_PIM", "SKU", "", ""),
            (2, "Color", "ENUM", "Color", "", ""),
            (3, "League", "ENUM", "", "", ""),
            (4, "Brand", "ENUM_FROM_PIM", "Color", "", ""),
            (5, "Theme", "ENUM_AI", "", "", ""),
            (6, "Notes", "AI_TEXT", "Color", "", ""),
        ],
    )
    mapping = parse_mapping_workbook(path, MarketplaceId.AMAZON)
    by_index = {r.column_index: r for r in mapping.listing_rows}
    assert by_index[2].fill_mode == FillMode.ENUM
    assert by_index[2].pim_field == "Color"
    assert by_index[3].fill_mode == FillMode.ENUM
    assert by_index[3].pim_field is None
    assert by_index[4].fill_mode == FillMode.ENUM_FROM_PIM
    assert by_index[5].fill_mode == FillMode.ENUM_AI
    assert by_index[6].fill_mode == FillMode.AI_TEXT
    assert by_index[6].pim_field == "Color"


def test_parse_mapping_workbook_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "map.xlsx"
    _write_mapping(
        path,
        rows=[
            (1, "Seller SKU", "COPY_PIM", "SKU", "", ""),
            (2, "Color", "ENUM", "Color", "", ""),
        ],
    )
    mapping = parse_mapping_workbook(path, MarketplaceId.AMAZON)
    assert len(mapping.pim_fields) == 2
    assert len(mapping.marketplace_columns) == 2
    assert mapping.listing_rows[0].column_index == 1
    assert mapping.listing_rows[1].fill_mode == FillMode.ENUM
    assert mapping.listing_rows[1].pim_field == "Color"


def test_build_columns_flipkart_index_and_dropdown_sheets(tmp_path: Path) -> None:
    path = tmp_path / "bedsheet.xlsx"
    wb = Workbook()
    ws_idx = wb.active
    ws_idx.title = "Index"
    ws_idx["A1"] = "Sub-categories in the file"
    ws_idx["C1"] = "Allowed Values"
    ws_idx["D1"] = "Bedsheet"
    ws_idx["A2"] = "bedsheet"
    ws_idx["D2"] = "Color"
    ws_idx["D3"] = "Red"
    ws_idx["D4"] = "Blue"
    ws = wb.create_sheet("bedsheet")
    ws["A1"] = "Seller SKU ID"
    ws["B1"] = "Country Of Origin"
    ws["C1"] = "Color"
    ws["D1"] = "Main Image URL"
    ws["E1"] = "Washable"
    ws["A2"] = "Text"
    ws["B2"] = "Single - Text"
    ws["C2"] = "Click Here to get Allowed Values"
    ws["D2"] = "URL"
    ws["E2"] = "Single - Boolean"
    dd = wb.create_sheet("DropDownValuesForColumn1")
    dd["A1"] = "India"
    dd["A2"] = "China"
    bogus = wb.create_sheet("DropDownValuesForColumn3")
    bogus["A1"] = "should-not-attach-to-url-column"
    wb.save(path)

    columns = build_columns(
        path,
        layout=WorkbookLayout(
            sheet_name="bedsheet",
            header_label_row=1,
            machine_key_row=2,
            data_start_row=5,
            enum_discovery="flipkart",
        ),
        include_requiredness=False,
    )
    by_index = {c["column_index"]: c["config"] for c in columns}
    assert by_index[1]["fill_type"] == "DIRECT_MAP"
    assert by_index[2]["fill_type"] == "ENUM"
    assert by_index[2]["valid_values"] == ["India", "China"]
    assert by_index[3]["fill_type"] == "ENUM"
    assert by_index[3]["valid_values"] == ["Red", "Blue"]
    assert by_index[4]["fill_type"] == "DIRECT_MAP"
    assert by_index[5]["fill_type"] == "ENUM"
    assert by_index[5]["valid_values"] == ["Yes", "No"]


def test_build_columns_amazon_ignores_flipkart_dropdown_sheets(tmp_path: Path) -> None:
    """Amazon discovery must not treat Flipkart Index / column sheets as ENUM lists."""
    path = tmp_path / "amazon.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Template"
    ws["A4"] = "Seller SKU"
    ws["A5"] = "item_sku"
    ws["B4"] = "Color"
    ws["B5"] = "color_name"
    idx = wb.create_sheet("Index")
    idx["C1"] = "Allowed Values"
    idx["D2"] = "Color"
    idx["D3"] = "ShouldNotAttach"
    dd = wb.create_sheet("DropDownValuesForColumn1")
    dd["A1"] = "AlsoShouldNotAttach"
    wb.save(path)

    columns = build_columns(
        path,
        layout=WorkbookLayout(
            sheet_name="Template",
            header_label_row=4,
            machine_key_row=5,
            data_start_row=7,
            enum_discovery="amazon",
        ),
        include_requiredness=False,
    )
    by_index = {c["column_index"]: c["config"] for c in columns}
    assert by_index[1]["fill_type"] == "DIRECT_MAP"
    assert by_index[2]["fill_type"] == "DIRECT_MAP"
    assert "ShouldNotAttach" not in (by_index[2].get("valid_values") or [])
    assert "AlsoShouldNotAttach" not in (by_index[1].get("valid_values") or [])


def test_build_columns_myntra_masterdata_sheet_ranges(tmp_path: Path) -> None:
    path = tmp_path / "myntra.xlsx"
    wb = Workbook()
    listing = wb.active
    listing.title = "Bedsheets"
    listing["A3"] = "brand"
    listing["B3"] = "Country Of Origin"
    listing["C3"] = "notes"
    master = wb.create_sheet("masterdata")
    master["B2"] = "Reebok"
    master["B3"] = "Puma"
    master["D2"] = "India"
    master["D3"] = "China"
    brand_dv = DataValidation(type="list", formula1="masterdata!$B$2:$B$3")
    brand_dv.add("A4")
    origin_dv = DataValidation(type="list", formula1="masterdata!$D$2:$D$3")
    origin_dv.add("B4")
    listing.add_data_validation(brand_dv)
    listing.add_data_validation(origin_dv)
    wb.save(path)

    columns = build_columns(
        path,
        layout=WorkbookLayout(
            sheet_name="Bedsheets",
            header_label_row=3,
            machine_key_row=3,
            data_start_row=4,
            enum_discovery="myntra",
        ),
        include_requiredness=False,
    )
    by_index = {c["column_index"]: c["config"] for c in columns}
    assert by_index[1]["fill_type"] == "ENUM"
    assert by_index[1]["valid_values"] == ["Reebok", "Puma"]
    assert by_index[2]["fill_type"] == "ENUM"
    assert by_index[2]["valid_values"] == ["India", "China"]
    assert by_index[3]["fill_type"] == "DIRECT_MAP"
    assert "__UNRESOLVED_DROPDOWN__" not in (by_index[1].get("valid_values") or [])
