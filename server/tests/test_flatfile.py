import pytest

from core.exceptions import FlatfileValidationError
from utils.flatfile import validate_allowed_headers


def test_validate_allowed_headers_accepts_exact_allow_list_names() -> None:
    validate_allowed_headers(
        ["SKU", "Color", "Size", ""],
        frozenset({"SKU", "Color", "Size"}),
    )


def test_validate_allowed_headers_rejects_case_mismatch() -> None:
    with pytest.raises(FlatfileValidationError, match="unknown column\\(s\\): color"):
        validate_allowed_headers(["SKU", "color"], frozenset({"SKU", "Color"}))


def test_validate_allowed_headers_rejects_extra_column() -> None:
    with pytest.raises(FlatfileValidationError, match="unknown column\\(s\\): Extra"):
        validate_allowed_headers(
            ["SKU", "Color", "Extra"],
            frozenset({"SKU", "Color"}),
        )


def test_validate_allowed_headers_skips_blank_and_duplicate_headers() -> None:
    validate_allowed_headers(
        ["SKU", "Color", "", "Color"],
        frozenset({"Color"}),
    )
