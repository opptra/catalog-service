"""Async listing fill — estimates, in-process lock, GCS latest-file listing."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from core.clients.gcs import GcsObjectInfo
from dto.response.listing import ListingFillGap
from entities.catalog.attribute_enums import ListingFillGapReason
from services import listing as listing_service


def setup_function() -> None:
    listing_service._running_fills.clear()


def test_estimate_fill_minutes_scales_with_skus_and_workers() -> None:
    slow = listing_service.estimate_fill_minutes(sku_count=55, llm_stage_count=3, workers=4)
    fast = listing_service.estimate_fill_minutes(sku_count=55, llm_stage_count=3, workers=12)
    assert slow >= 1
    assert fast >= 1
    assert fast < slow


def test_estimate_fill_minutes_minimum_one() -> None:
    assert listing_service.estimate_fill_minutes(sku_count=0, llm_stage_count=3, workers=12) == 1
    assert listing_service.estimate_fill_minutes(sku_count=10, llm_stage_count=0, workers=12) == 1


def test_try_begin_listing_fill_rejects_second_start() -> None:
    job_id = uuid4()
    assert listing_service.try_begin_listing_fill(job_id) is True
    assert listing_service.try_begin_listing_fill(job_id) is False
    assert listing_service.is_listing_fill_running(job_id) is True
    listing_service.end_listing_fill(job_id)
    assert listing_service.is_listing_fill_running(job_id) is False
    assert listing_service.try_begin_listing_fill(job_id) is True
    listing_service.end_listing_fill(job_id)


def test_latest_listing_file_picks_newest_workbook() -> None:
    job_id = uuid4()
    marketplace_id = uuid4()
    older = datetime(2026, 1, 1, tzinfo=UTC)
    newer = datetime(2026, 9, 11, tzinfo=UTC)
    gcs = MagicMock()
    gcs.list_objects.return_value = [
        GcsObjectInfo(name=f"jobs/{job_id}/output/listing/gaps.json", updated=newer),
        GcsObjectInfo(
            name=f"jobs/{job_id}/output/listing/old_filled.xlsm",
            updated=older,
        ),
        GcsObjectInfo(
            name=f"jobs/{job_id}/output/listing/new_filled.xlsm",
            updated=newer,
        ),
    ]
    gcs.signed_url.return_value = "https://example.com/new_filled.xlsm"
    gcs.object_exists.return_value = True
    gcs.download_bytes.return_value = b"[]"

    item = listing_service._latest_listing_file_for_job(
        gcs,
        job_external_id=job_id,
        marketplace_external_id=marketplace_id,
        marketplace_name="Amazon",
    )

    assert item.filename == "new_filled.xlsm"
    assert item.filled_file_url == "https://example.com/new_filled.xlsm"
    assert item.generated_at == newer
    gcs.signed_url.assert_called_once_with(
        f"jobs/{job_id}/output/listing/new_filled.xlsm",
        expiration_seconds=3600,
    )


def test_load_gaps_sidecar_parses_valid_rows() -> None:
    job_id = uuid4()
    gcs = MagicMock()
    gcs.object_exists.return_value = True
    gcs.download_bytes.return_value = (
        b'[{"sku_id":"SKU-1","column_label":"Color","reason":"REQUIRED_EMPTY","message":"x"}]'
    )

    gaps = listing_service._load_gaps_sidecar(gcs, job_id)

    assert len(gaps) == 1
    assert gaps[0] == ListingFillGap(
        sku_id="SKU-1",
        column_label="Color",
        reason=ListingFillGapReason.REQUIRED_EMPTY,
    )


def test_run_listing_fill_background_releases_lock_on_failure() -> None:
    job_id = uuid4()
    assert listing_service.try_begin_listing_fill(job_id) is True
    session = MagicMock()
    session_factory = MagicMock(return_value=session)

    with patch(
        "services.listing.fill_listing_for_job",
        side_effect=RuntimeError("boom"),
    ):
        listing_service.run_listing_fill_background(
            session_factory,
            MagicMock(),
            MagicMock(),
            MagicMock(),
            job_id,
        )

    assert listing_service.is_listing_fill_running(job_id) is False
    session.close.assert_called_once()
