"""Rebuild the wizard product CSV + images ZIP for a generation job.

Job → sku_generation_job → sku_master.attributes. Source photos are listed
under ``products/{SKU}/assets/images/`` in GCS (the original flatfile uploads).
"""

from __future__ import annotations

import csv
import json
import logging
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from core.exceptions.export_job_inputs import JobInputExportError
from core.exceptions.gcs import GcsError
from core.exceptions.job import FlatfileValidationError
from entities.catalog.attribute_enums import JobType
from entities.catalog.sku_master import SkuMaster
from repositories.catalog import job as job_repo
from repositories.catalog import sku_generation_job as sku_generation_job_repo
from repositories.catalog import sku_master as sku_master_repo
from utils.flatfile import cell_str, product_image_prefix, safe_sku_id

logger = logging.getLogger(__name__)

ATTRIBUTES_CSV_NAME = "attributes.csv"
IMAGES_ZIP_NAME = "images.zip"
# Wizard + inbound QC unwrap a single top-level folder. Keep one so 1-SKU zips work.
_ZIP_ROOT = "images"


class GcsObjectStore(Protocol):
    """Read-only GCS surface used by this exporter."""

    def list_object_names(self, prefix: str) -> list[str]: ...

    def download_bytes(self, object_name: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class JobInputExport:
    job_external_id: UUID
    sku_ids: tuple[str, ...]
    attributes_csv: Path
    images_zip: Path
    missing_image_sku_ids: tuple[str, ...]


def export_job_inputs(
    session: Session,
    gcs: GcsObjectStore,
    job_external_id: UUID,
    out_dir: Path,
    *,
    limit: int | None = None,
) -> JobInputExport:
    """Write ``attributes.csv`` + ``images.zip`` under ``out_dir`` for one job."""
    if limit is not None and limit < 1:
        raise JobInputExportError("limit must be a positive integer")

    logger.info("job %s — loading SKUs", job_external_id)
    skus = load_job_skus(session, job_external_id, limit=limit)
    headers, rows = rows_from_skus(skus)
    logger.info("attributes ready — %s SKU(s), %s columns", len(rows), len(headers))

    images_by_sku: dict[str, list[tuple[str, bytes]]] = {}
    missing: list[str] = []
    total = len(rows)
    photo_count = 0
    for index, row in enumerate(rows, start=1):
        sku_id = row["SKU"]
        logger.info("photos %s/%s %s — listing GCS", index, total, sku_id)
        files = download_sku_images(gcs, sku_id)
        images_by_sku[sku_id] = files
        size = sum(len(content) for _name, content in files)
        photo_count += len(files)
        if not files:
            missing.append(sku_id)
            logger.warning("photos %s/%s %s — none found", index, total, sku_id)
        else:
            logger.info(
                "photos %s/%s %s — %s file(s) (%s)",
                index,
                total,
                sku_id,
                len(files),
                _format_bytes(size),
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = write_attributes_csv(out_dir / ATTRIBUTES_CSV_NAME, headers, rows)
    logger.info("wrote %s (%s)", csv_path.name, _format_bytes(csv_path.stat().st_size))
    zip_path = write_images_zip(out_dir / IMAGES_ZIP_NAME, images_by_sku)
    logger.info(
        "wrote %s (%s, %s file(s))",
        zip_path.name,
        _format_bytes(zip_path.stat().st_size),
        photo_count,
    )
    if missing:
        logger.warning("%s SKU(s) had no source photos", len(missing))
    logger.info("done — %s SKU(s) → %s", len(rows), out_dir)
    return JobInputExport(
        job_external_id=job_external_id,
        sku_ids=tuple(row["SKU"] for row in rows),
        attributes_csv=csv_path,
        images_zip=zip_path,
        missing_image_sku_ids=tuple(missing),
    )


def load_job_skus(
    session: Session,
    job_external_id: UUID,
    *,
    limit: int | None = None,
) -> list[SkuMaster]:
    """SKUs attached to a GENERATION job, in sku_generation_job order."""
    job = job_repo.get_by_external_id(session, job_external_id)
    if job is None:
        raise JobInputExportError(f"Job not found: {job_external_id}")
    if job.job_type != JobType.GENERATION.value:
        raise JobInputExportError(
            f"Job {job_external_id} is {job.job_type}; pass a GENERATION job external_id"
        )

    sku_jobs = list(sku_generation_job_repo.list_by_job_id(session, job.id))
    if not sku_jobs:
        raise JobInputExportError(f"Job {job_external_id} has no sku_generation_job rows")

    ordered_ids = [row.sku_id for row in sku_jobs]
    found = {sku.id: sku for sku in sku_master_repo.list_by_ids(session, ordered_ids)}
    missing_pks = [sku_id for sku_id in ordered_ids if sku_id not in found]
    if missing_pks:
        logger.warning(
            "job %s SKU pk(s) missing or deleted: %s",
            job_external_id,
            missing_pks,
        )

    skus: list[SkuMaster] = []
    for sku_id in ordered_ids:
        sku = found.get(sku_id)
        if sku is None:
            continue
        skus.append(sku)
        if limit is not None and len(skus) >= limit:
            break
    if not skus:
        raise JobInputExportError(f"Job {job_external_id} has no live sku_master rows")

    live_count = sum(1 for sku_id in ordered_ids if sku_id in found)
    if limit is not None and live_count > len(skus):
        logger.info(
            "job %s — %s live SKU(s), exporting first %s",
            job_external_id,
            live_count,
            len(skus),
        )
    else:
        logger.info("job %s — %s live SKU(s)", job_external_id, len(skus))
    return skus


def rows_from_skus(skus: Sequence[SkuMaster]) -> tuple[list[str], list[dict[str, str]]]:
    """Flatten ``sku_master.attributes`` into CSV headers + rows. ``SKU`` is first."""
    rows: list[dict[str, str]] = []
    extra_headers: list[str] = []
    seen_headers: set[str] = set()
    seen_skus: set[str] = set()

    for sku in skus:
        attributes = dict(sku.attributes or {})
        raw_sku = str(attributes.get("SKU") or "").strip()
        if not raw_sku:
            logger.warning("sku_master id=%s is missing attributes.SKU; skipped", sku.id)
            continue
        try:
            sku_id = safe_sku_id(raw_sku)
        except FlatfileValidationError:
            logger.warning("sku_master id=%s has invalid SKU %r; skipped", sku.id, raw_sku)
            continue
        if sku_id in seen_skus:
            logger.warning("duplicate attributes.SKU %s; later row skipped", sku_id)
            continue
        seen_skus.add(sku_id)

        row: dict[str, str] = {"SKU": sku_id}
        for key, value in attributes.items():
            if not key or key == "SKU":
                continue
            if key not in seen_headers:
                extra_headers.append(key)
                seen_headers.add(key)
            row[key] = _cell_value(value)
        rows.append(row)

    if not rows:
        raise JobInputExportError("No sku_master rows with attributes.SKU")
    return ["SKU", *extra_headers], rows


def download_sku_images(gcs: GcsObjectStore, sku_id: str) -> list[tuple[str, bytes]]:
    """Download original product photos for ``sku_id`` (business SKU, not PK)."""
    prefix = product_image_prefix(sku_id)
    try:
        object_names = sorted(gcs.list_object_names(prefix))
    except GcsError as exc:
        raise JobInputExportError(f"GCS list failed for {prefix!r}: {exc}") from exc

    files: list[tuple[str, bytes]] = []
    for object_name in object_names:
        filename = object_name.rsplit("/", 1)[-1]
        if not filename:
            continue
        try:
            content = gcs.download_bytes(object_name)
        except GcsError as exc:
            raise JobInputExportError(f"GCS download failed for {object_name!r}: {exc}") from exc
        files.append((filename, content))
    return files


def write_attributes_csv(
    path: Path,
    headers: list[str],
    rows: list[dict[str, str]],
) -> Path:
    """Write a wizard-compatible CSV (UTF-8 BOM, ``SKU`` column required)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_images_zip(
    path: Path,
    images_by_sku: dict[str, list[tuple[str, bytes]]],
) -> Path:
    """Write ``images/{SKU}/{filename}`` — wizard layout (root folder + SKU folders)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for sku_id, files in images_by_sku.items():
            if not files:
                archive.writestr(f"{_ZIP_ROOT}/{sku_id}/", b"")
                continue
            for filename, content in files:
                archive.writestr(f"{_ZIP_ROOT}/{sku_id}/{filename}", content)
    return path


def _cell_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return cell_str(value)


def _format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"
