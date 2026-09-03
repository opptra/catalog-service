"""Tests for marketplace workbook config + Amazon adapter."""

from __future__ import annotations

import pytest
from listing_mapping.marketplace import MarketplaceId
from listing_mapping.marketplace.config import clear_config_cache, config_for
from listing_mapping.marketplace.registry import get_adapter


def setup_function() -> None:
    clear_config_cache()


def teardown_function() -> None:
    clear_config_cache()


def test_amazon_config_sheets() -> None:
    cfg = config_for(MarketplaceId.AMAZON)
    assert cfg.valid_values_sheet == "Valid Values"
    assert cfg.dropdown_lists_sheet == "Dropdown Lists"
    assert cfg.data_definitions_sheet == "Data Definitions"
    assert cfg.sheet_name == "Template"


def test_amazon_adapter_uses_config() -> None:
    layout = get_adapter(MarketplaceId.AMAZON).workbook_layout()
    assert layout.valid_values_sheet == "Valid Values"
    assert layout.data_start_row == 7


def test_unknown_marketplace_config_fails() -> None:
    with pytest.raises(ValueError, match="No workbook config"):
        config_for(MarketplaceId.MYNTRA)


def test_flipkart_config_layout() -> None:
    cfg = config_for(MarketplaceId.FLIPKART)
    assert cfg.sheet_name == "bedsheet"
    assert cfg.header_label_row == 1
    assert cfg.data_start_row == 5
    assert cfg.valid_values_sheet is None


def test_flipkart_adapter_uses_config() -> None:
    layout = get_adapter(MarketplaceId.FLIPKART).workbook_layout()
    assert layout.sheet_name == "bedsheet"
    assert layout.data_start_row == 5
