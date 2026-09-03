"""AI_TEXT optional SKU_MASTER source: config + fill short-circuit."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from dto.listing_config import ListingColumnConfig
from entities.catalog.attribute_enums import ListingFillType, ListingValueSourceFrom
from services.listing import _ParsedColumn, _resolve_stage


def test_ai_text_allows_sku_master_source() -> None:
    cfg = ListingColumnConfig.model_validate(
        {
            "fill_type": "AI_TEXT",
            "label": "Fabric Type",
            "source": {"from": "SKU_MASTER", "key": "Material"},
        }
    )
    assert cfg.fill_type == ListingFillType.AI_TEXT
    assert cfg.source is not None
    assert cfg.source.from_ == ListingValueSourceFrom.SKU_MASTER
    assert cfg.source.key == "Material"


def test_ai_text_rejects_generation_source() -> None:
    with pytest.raises(ValidationError, match="SKU_MASTER"):
        ListingColumnConfig.model_validate(
            {
                "fill_type": "AI_TEXT",
                "label": "Fabric Type",
                "source": {
                    "from": "GENERATION",
                    "attribute_name": "TITLE",
                    "slot": 1,
                },
            }
        )


def test_ai_text_still_forbids_constant_value() -> None:
    with pytest.raises(ValidationError, match="constant_value"):
        ListingColumnConfig.model_validate(
            {
                "fill_type": "AI_TEXT",
                "label": "Fabric Type",
                "constant_value": "nope",
            }
        )


def _ai_col(
    column_index: int,
    label: str,
    *,
    source_key: str | None = None,
) -> _ParsedColumn:
    raw: dict = {"fill_type": "AI_TEXT", "label": label}
    if source_key is not None:
        raw["source"] = {"from": "SKU_MASTER", "key": source_key}
    return _ParsedColumn(column_index, 1, ListingColumnConfig.model_validate(raw))


def test_resolve_stage_ai_text_copies_nonempty_pim() -> None:
    col = _ai_col(1, "Fabric Type", source_key="Material")
    with patch("services.listing.ai_text.generate_texts") as generate:
        results = _resolve_stage(
            [col],
            gcs=MagicMock(),
            dropbox=MagicMock(),
            openrouter=MagicMock(),
            business_sku_id="SKU-1",
            pim_values={"Material": "  Cotton  "},
            job_values={},
            already_filled={},
            already_filled_by_index={},
            product_image_urls=[],
        )
    generate.assert_not_called()
    assert results == [(1, "Cotton", None, "Fabric Type")]


def test_resolve_stage_ai_text_empty_pim_falls_back_to_generate() -> None:
    col = _ai_col(1, "Fabric Type", source_key="Material")
    with patch(
        "services.listing.ai_text.generate_texts",
        return_value={1: "soft cotton weave"},
    ) as generate:
        results = _resolve_stage(
            [col],
            gcs=MagicMock(),
            dropbox=MagicMock(),
            openrouter=MagicMock(),
            business_sku_id="SKU-1",
            pim_values={"Material": "  "},
            job_values={},
            already_filled={},
            already_filled_by_index={},
            product_image_urls=[],
        )
    generate.assert_called_once()
    assert results == [(1, "soft cotton weave", None, "Fabric Type")]


def test_resolve_stage_ai_text_without_source_always_generates() -> None:
    col = _ai_col(1, "Notes")
    with patch(
        "services.listing.ai_text.generate_texts",
        return_value={1: "generated"},
    ) as generate:
        results = _resolve_stage(
            [col],
            gcs=MagicMock(),
            dropbox=MagicMock(),
            openrouter=MagicMock(),
            business_sku_id="SKU-1",
            pim_values={"Material": "Cotton"},
            job_values={},
            already_filled={},
            already_filled_by_index={},
            product_image_urls=[],
        )
    generate.assert_called_once()
    assert results == [(1, "generated", None, "Notes")]
