"""Tests for ops listing-workbook marketplace sheet config."""

from __future__ import annotations

import pytest
from listing_mapping.marketplace_workbook import (
    clear_sheets_cache,
    list_marketplace_keys,
    sheets_for_marketplace,
)


def setup_function() -> None:
    clear_sheets_cache()


def teardown_function() -> None:
    clear_sheets_cache()


def test_amazon_sheets_from_config() -> None:
    sheets = sheets_for_marketplace("Amazon")
    assert sheets.valid_values_sheet == "Valid Values"
    assert sheets.dropdown_lists_sheet == "Dropdown Lists"
    assert sheets.data_definitions_sheet == "Data Definitions"


def test_marketplace_lookup_is_case_insensitive() -> None:
    sheets = sheets_for_marketplace("amazon")
    assert sheets.valid_values_sheet == "Valid Values"


def test_unknown_marketplace_fails() -> None:
    with pytest.raises(ValueError, match="No listing-workbook config"):
        sheets_for_marketplace("NotAMarketplace")


def test_list_marketplace_keys_includes_amazon() -> None:
    assert any(key.casefold() == "amazon" for key in list_marketplace_keys())
