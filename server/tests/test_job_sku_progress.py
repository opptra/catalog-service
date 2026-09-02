from types import SimpleNamespace

from services.job import _unique_sku_progress


def test_unique_sku_progress_does_not_treat_marketplaces_as_separate_skus() -> None:
    """Amazon done + Myntra pending is still 1 pending SKU, not 1 of 1 + 1 pending."""
    rows = [
        SimpleNamespace(sku_id=1, status="COMPLETED"),
        SimpleNamespace(sku_id=1, status="PENDING"),
    ]
    assert _unique_sku_progress(rows) == {
        "total": 1,
        "completed": 0,
        "failed": 0,
        "pending": 1,
    }


def test_unique_sku_progress_completed_only_when_every_marketplace_finished() -> None:
    rows = [
        SimpleNamespace(sku_id=1, status="COMPLETED"),
        SimpleNamespace(sku_id=1, status="COMPLETED"),
        SimpleNamespace(sku_id=2, status="COMPLETED"),
        SimpleNamespace(sku_id=2, status="FAILED"),
    ]
    assert _unique_sku_progress(rows) == {
        "total": 2,
        "completed": 1,
        "failed": 1,
        "pending": 0,
    }


def test_unique_sku_progress_empty() -> None:
    assert _unique_sku_progress([]) == {
        "total": 0,
        "completed": 0,
        "failed": 0,
        "pending": 0,
    }
