"""Marketplace listing-workbook layout + upload metadata."""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from utils.listing_marketplace import (
    listing_upload_filename,
    marketplace_key_from_name,
    metadata_for_listing_upload,
)
from utils.listing_workbook import content_type_for


def _xlsx_bytes(*sheet_names: str) -> bytes:
    workbook = Workbook()
    workbook.active.title = sheet_names[0]
    for name in sheet_names[1:]:
        workbook.create_sheet(name)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_marketplace_key_from_name() -> None:
    assert marketplace_key_from_name("Amazon") == "AMAZON"
    assert marketplace_key_from_name("flipkart") == "FLIPKART"
    assert marketplace_key_from_name("Myntra") == "MYNTRA"


def test_marketplace_key_unknown() -> None:
    with pytest.raises(ValueError, match="Cannot resolve"):
        marketplace_key_from_name("Noon")


def test_listing_upload_filename_stamps_detected_kind() -> None:
    assert listing_upload_filename("Flipkart Listing File - Bedsheet.xls", "xlsm") == (
        "Flipkart Listing File - Bedsheet.xlsm"
    )
    assert listing_upload_filename("listing-template.xlsx", "xlsx") == "listing-template.xlsx"


def test_content_type_for_xlsm() -> None:
    assert content_type_for("xlsm") == "application/vnd.ms-excel.sheet.macroEnabled.12"


def test_flipkart_upload_metadata_uses_adapter_offsets() -> None:
    content = _xlsx_bytes("bedsheet", "Index")
    metadata = metadata_for_listing_upload(
        marketplace_name="Flipkart",
        content=content,
        original_filename="Flipkart Listing File - Bedsheet.xlsm",
    )
    assert metadata.sheet_name == "bedsheet"
    assert metadata.header_label_row == 1
    assert metadata.machine_key_row == 2
    assert metadata.data_start_row == 5
    assert metadata.filename == "Flipkart Listing File - Bedsheet.xlsx"


def test_flipkart_upload_keeps_existing_sheet_when_present() -> None:
    content = _xlsx_bytes("curtain", "Index")
    metadata = metadata_for_listing_upload(
        marketplace_name="Flipkart",
        content=content,
        original_filename="curtain.xlsm",
        existing_metadata={
            "filename": "listing-template.xlsx",
            "sheet_name": "curtain",
            "header_label_row": 1,
            "machine_key_row": 2,
            "data_start_row": 5,
        },
    )
    assert metadata.sheet_name == "curtain"
    assert metadata.data_start_row == 5
    assert metadata.filename == "curtain.xlsx"


def test_flipkart_upload_replaces_amazon_defaults_when_sheet_missing() -> None:
    content = _xlsx_bytes("bedsheet")
    metadata = metadata_for_listing_upload(
        marketplace_name="Flipkart",
        content=content,
        original_filename="bedsheet.xlsm",
        existing_metadata={
            "filename": "listing-template.xlsx",
            "sheet_name": "Template",
            "header_label_row": 4,
            "machine_key_row": 5,
            "data_start_row": 7,
        },
    )
    assert metadata.sheet_name == "bedsheet"
    assert metadata.header_label_row == 1
    assert metadata.data_start_row == 5
