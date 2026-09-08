"""Listing-fill gap codes and oversized-dropdown skip."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dto.listing_config import ListingColumnConfig
from dto.response.listing import ListingFillGap
from entities.catalog.attribute_enums import (
    LISTING_FILL_GAP_MESSAGES,
    ListingFillGapReason,
)
from services.listing import _ENUM_AI_MAX_VALUES, _ParsedColumn, _resolve_stage


def test_gap_messages_cover_every_reason() -> None:
    assert set(LISTING_FILL_GAP_MESSAGES) == set(ListingFillGapReason)


def test_listing_fill_gap_message_comes_from_reason() -> None:
    gap = ListingFillGap(
        sku_id="SKU-1",
        column_label="Brand",
        reason=ListingFillGapReason.TOO_MANY_DROPDOWN_VALUES,
        message="ignored",
    )
    assert gap.reason == ListingFillGapReason.TOO_MANY_DROPDOWN_VALUES
    assert gap.message == ListingFillGapReason.TOO_MANY_DROPDOWN_VALUES.message


def _enum_col(
    column_index: int,
    label: str,
    valid_values: list[str],
    *,
    source_key: str | None = None,
) -> _ParsedColumn:
    raw: dict = {
        "fill_type": "ENUM",
        "label": label,
        "valid_values": valid_values,
    }
    if source_key is not None:
        raw["source"] = {"from": "SKU_MASTER", "key": source_key}
    return _ParsedColumn(column_index, 1, ListingColumnConfig.model_validate(raw))


def _oversized_values(*, include: str | None = None) -> list[str]:
    values = [f"opt-{i:03d}" for i in range(_ENUM_AI_MAX_VALUES + 1)]
    if include is not None:
        values[0] = include
    return values


def test_oversized_dropdown_skips_ai_and_reports_gap() -> None:
    col = _enum_col(1, "Brand", _oversized_values(), source_key="Brand")
    with patch("services.listing.enum_select.pick_enums") as pick:
        results = _resolve_stage(
            [col],
            gcs=MagicMock(),
            dropbox=MagicMock(),
            openrouter=MagicMock(),
            business_sku_id="SKU-1",
            pim_values={"Brand": "Unknown"},
            job_values={},
            already_filled={},
            already_filled_by_index={},
            product_image_urls=[],
        )
    pick.assert_not_called()
    assert results == [
        (1, None, ListingFillGapReason.TOO_MANY_DROPDOWN_VALUES, "Brand"),
    ]


def test_oversized_dropdown_still_fills_exact_pim_match() -> None:
    col = _enum_col(1, "Brand", _oversized_values(include="Nike"), source_key="Brand")
    with patch("services.listing.enum_select.pick_enums") as pick:
        results = _resolve_stage(
            [col],
            gcs=MagicMock(),
            dropbox=MagicMock(),
            openrouter=MagicMock(),
            business_sku_id="SKU-1",
            pim_values={"Brand": "nike"},
            job_values={},
            already_filled={},
            already_filled_by_index={},
            product_image_urls=[],
        )
    pick.assert_not_called()
    assert results == [(1, "Nike", None, "Brand")]


def test_dropdown_at_ai_cap_still_calls_model() -> None:
    values = [f"opt-{i:03d}" for i in range(_ENUM_AI_MAX_VALUES)]
    col = _enum_col(1, "Color", values, source_key="Color")
    with patch(
        "services.listing.enum_select.pick_enums",
        return_value={1: values[0]},
    ) as pick:
        results = _resolve_stage(
            [col],
            gcs=MagicMock(),
            dropbox=MagicMock(),
            openrouter=MagicMock(),
            business_sku_id="SKU-1",
            pim_values={"Color": "no-match"},
            job_values={},
            already_filled={},
            already_filled_by_index={},
            product_image_urls=[],
        )
    pick.assert_called_once()
    assert results == [(1, values[0], None, "Color")]
