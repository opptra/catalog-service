"""Fill listing workbooks for .xlsx and Excel 97-2003 .xls templates."""

from __future__ import annotations

import io
from zipfile import ZipFile

import pytest
import xlrd
import xlwt
from openpyxl import Workbook, load_workbook
from xlwt import easyxf

from dto.listing_config import ListingTemplateMetadata
from utils.listing_workbook import fill_workbook


def _xls_bytes(*, sheet_name: str, header: str, extra_sheets: list[str] | None = None) -> bytes:
    book = xlwt.Workbook(encoding="utf-8")
    sheet = book.add_sheet(sheet_name)
    header_style = easyxf("pattern: pattern solid, fore_colour yellow; font: bold on")
    data_style = easyxf("pattern: pattern solid, fore_colour gray25")
    sheet.write(0, 0, header, header_style)
    sheet.write(4, 0, "", data_style)
    for name in extra_sheets or []:
        extra = book.add_sheet(name)
        extra.write(0, 0, "dropdown")
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _xlsx_bytes(*, sheet_name: str, header: str) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet_name
    worksheet.cell(4, 1, header)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_fill_xls_writes_data_row_and_keeps_xls() -> None:
    metadata = ListingTemplateMetadata(
        filename="Flipkart Listing File - Bedsheet.xls",
        sheet_name="bedsheet",
        header_label_row=1,
        machine_key_row=2,
        data_start_row=5,
    )
    template = _xls_bytes(
        sheet_name="bedsheet",
        header="SKU",
        extra_sheets=["DropDownValuesForColumn0"],
    )

    filled = fill_workbook(template, metadata=metadata, rows=[{1: "CLOUDTOUCH-KING"}])

    assert filled.filename == "Flipkart Listing File - Bedsheet_filled.xls"
    assert filled.content_type == "application/vnd.ms-excel"
    assert filled.content.startswith(b"\xd0\xcf\x11\xe0")

    book = xlrd.open_workbook(file_contents=filled.content)
    assert book.sheet_names() == ["bedsheet", "DropDownValuesForColumn0"]
    data = book.sheet_by_name("bedsheet")
    assert data.cell_value(0, 0) == "SKU"
    assert data.cell_value(4, 0) == "CLOUDTOUCH-KING"
    extra = book.sheet_by_name("DropDownValuesForColumn0")
    assert extra.cell_value(0, 0) == "dropdown"

    styled = xlrd.open_workbook(file_contents=filled.content, formatting_info=True)
    header_sheet = styled.sheet_by_name("bedsheet")
    header_xf = styled.xf_list[header_sheet.cell_xf_index(0, 0)]
    data_xf = styled.xf_list[header_sheet.cell_xf_index(4, 0)]
    assert header_xf.background.fill_pattern == 1
    assert data_xf.background.fill_pattern == 1


def test_fill_xlsx_still_writes_openxml() -> None:
    metadata = ListingTemplateMetadata(
        filename="listing-template.xlsx",
        sheet_name="Template",
        data_start_row=7,
    )
    template = _xlsx_bytes(sheet_name="Template", header="item_sku")

    filled = fill_workbook(template, metadata=metadata, rows=[{1: "SKU-1"}])

    assert filled.filename == "listing-template_filled.xlsx"
    assert filled.content_type == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert filled.content.startswith(b"PK")

    workbook = load_workbook(io.BytesIO(filled.content))
    assert workbook["Template"].cell(7, 1).value == "SKU-1"


def test_fill_xlsx_does_not_mark_file_as_macro_enabled() -> None:
    metadata = ListingTemplateMetadata(
        filename="Myntra Listing File - Bedsheet.xlsx",
        sheet_name="Bedsheets",
        header_label_row=3,
        machine_key_row=3,
        data_start_row=4,
    )
    template = _xlsx_bytes(sheet_name="Bedsheets", header="styleid")
    filled = fill_workbook(template, metadata=metadata, rows=[{1: "SKU-1"}])

    assert filled.filename.endswith(".xlsx")
    with ZipFile(io.BytesIO(filled.content)) as archive:
        content_types = archive.read("[Content_Types].xml").decode()
        rels = archive.read("xl/_rels/workbook.xml.rels").decode()
    assert "macroEnabled" not in content_types
    assert "vbaProject" not in rels


def test_fill_rejects_non_excel_bytes() -> None:
    metadata = ListingTemplateMetadata(filename="listing.xls", sheet_name="bedsheet")
    with pytest.raises(ValueError, match="not an Excel workbook"):
        fill_workbook(b"not-excel", metadata=metadata, rows=[])


def test_fill_missing_sheet() -> None:
    metadata = ListingTemplateMetadata(
        filename="flipkart.xls",
        sheet_name="bedsheet",
        data_start_row=5,
    )
    template = _xls_bytes(sheet_name="other", header="SKU")
    with pytest.raises(ValueError, match="Sheet 'bedsheet' not found"):
        fill_workbook(template, metadata=metadata, rows=[{1: "x"}])
