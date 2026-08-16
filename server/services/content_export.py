"""Job content export — dynamic columns from job_attributes for UI sheet download."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from core.clients.dropbox import MAX_CONCURRENT_OPS, DropboxClient
from core.clients.gcs import GcsClient
from core.exceptions import DropboxError, GcsError, JobNotFoundError
from entities.catalog.attribute_enums import AttributeDataType
from entities.catalog.attribute_master import AttributeMaster
from entities.catalog.job_attribute import JobAttribute
from entities.catalog.sku_master import SkuMaster
from repositories.catalog import attribute_master as attribute_master_repo
from repositories.catalog import job as job_repo
from repositories.catalog import job_attribute as job_attribute_repo
from repositories.catalog import marketplace as marketplace_repo
from repositories.catalog import sku_generation_job as sku_generation_job_repo
from repositories.catalog import sku_marketplace_attribute_value as attribute_value_repo
from repositories.catalog import sku_master as sku_master_repo
from services import attribute as attribute_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ImageEnsureTask:
    row_index: int
    column_key: str
    gs_uri: str
    attribute_value_external_id: UUID


def export_job_content(
    session: Session,
    gcs: GcsClient,
    dropbox: DropboxClient,
    job_external_id: UUID,
) -> dict[str, Any]:
    """Build dynamic columns + rows for all SKUs on a generation job.

    Columns come from ``job_attribute`` (what was selected for generation). IMAGE
    cells are Dropbox ``dl=1`` URLs via ``ensure_shared_url``, resolved with the
    same concurrency cap as listing fill (``MAX_CONCURRENT_OPS``).
    """
    job = job_repo.get_by_external_id(session, job_external_id)
    if job is None:
        raise JobNotFoundError(f"Job not found: {job_external_id}")

    job_attributes = list(job_attribute_repo.list_by_job_id(session, job.id))
    attribute_ids = [ja.attribute_id for ja in job_attributes]
    masters = {
        master.id: master for master in attribute_master_repo.list_by_ids(session, attribute_ids)
    }

    columns = _build_columns(job_attributes, masters)
    column_keys = [col["key"] for col in columns]

    marketplace = (
        marketplace_repo.get_by_id(session, job.marketplace_id)
        if job.marketplace_id is not None
        else None
    )

    sku_jobs = list(sku_generation_job_repo.list_by_job_id(session, job.id))
    rows: list[dict[str, str | None]] = []
    image_tasks: list[_ImageEnsureTask] = []

    for sku_job in sku_jobs:
        sku = sku_master_repo.get_by_id(session, sku_job.sku_id)
        business_id = _business_sku_id(sku, fallback=str(sku_job.sku_id))
        row: dict[str, str | None] = dict.fromkeys(column_keys)
        row["sku_id"] = business_id
        row["display_name"] = _display_name(sku, business_id)

        value_rows = attribute_value_repo.list_latest_by_sku_generation_job_id(session, sku_job.id)
        values_by_key = {(row_av.attribute_id, row_av.slot): row_av for row_av in value_rows}

        row_index = len(rows)
        for ja in job_attributes:
            master = masters.get(ja.attribute_id)
            if master is None:
                continue
            for slot in range(1, ja.quantity + 1):
                key = _column_key(master.name.value, slot, ja.quantity)
                av = values_by_key.get((master.id, slot))
                if av is None or not av.value:
                    continue
                if master.data_type == AttributeDataType.IMAGE:
                    image_tasks.append(
                        _ImageEnsureTask(
                            row_index=row_index,
                            column_key=key,
                            gs_uri=av.value,
                            attribute_value_external_id=av.external_id,
                        )
                    )
                else:
                    row[key] = _format_text_value(av.value)

        rows.append(row)

    _fill_image_urls(rows, image_tasks, gcs=gcs, dropbox=dropbox)

    return {
        "job_external_id": job.external_id,
        "marketplace_external_id": marketplace.external_id if marketplace else None,
        "marketplace_name": marketplace.name if marketplace else None,
        "columns": columns,
        "rows": rows,
    }


def _fill_image_urls(
    rows: list[dict[str, str | None]],
    tasks: list[_ImageEnsureTask],
    *,
    gcs: GcsClient,
    dropbox: DropboxClient,
) -> None:
    if not tasks:
        return
    workers = min(dropbox.max_concurrent_ops, MAX_CONCURRENT_OPS, max(1, len(tasks)))

    def _run(task: _ImageEnsureTask) -> tuple[int, str, str | None]:
        url = _image_to_dropbox_url(
            gcs,
            dropbox,
            gs_uri=task.gs_uri,
            attribute_value_external_id=task.attribute_value_external_id,
        )
        return task.row_index, task.column_key, url

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_run, task) for task in tasks]
        for future in as_completed(futures):
            row_index, column_key, url = future.result()
            rows[row_index][column_key] = url


def _build_columns(
    job_attributes: list[JobAttribute],
    masters: dict[int, AttributeMaster],
) -> list[dict[str, str]]:
    columns: list[dict[str, str]] = [
        {"key": "sku_id", "label": "SKU ID", "data_type": "TEXT"},
        {"key": "display_name", "label": "Display name", "data_type": "TEXT"},
    ]
    for ja in job_attributes:
        master = masters.get(ja.attribute_id)
        if master is None:
            continue
        name = master.name.value
        base_label = attribute_service.display_label(name)
        for slot in range(1, ja.quantity + 1):
            key = _column_key(name, slot, ja.quantity)
            label = base_label if ja.quantity == 1 else f"{base_label} {slot}"
            columns.append(
                {
                    "key": key,
                    "label": label,
                    "data_type": master.data_type.value,
                }
            )
    return columns


def _column_key(name: str, slot: int, quantity: int) -> str:
    if quantity == 1:
        return name
    return f"{name}_{slot}"


def _format_text_value(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(parsed, list):
            parts = [str(item).strip() for item in parsed if item is not None and str(item).strip()]
            return "\n".join(parts)
    return text


def _image_to_dropbox_url(
    gcs: GcsClient,
    dropbox: DropboxClient,
    *,
    gs_uri: str,
    attribute_value_external_id: UUID,
) -> str | None:
    if not gs_uri.startswith("gs://"):
        return gs_uri if gs_uri.startswith("http") else None
    object_name = gcs.object_name_from_gs_uri(gs_uri)
    if object_name is None:
        logger.warning("Invalid image GCS URI for export: %s", gs_uri)
        return None

    ext = "png"
    lower = object_name.lower()
    for candidate in ("png", "jpg", "jpeg", "webp", "gif"):
        if lower.endswith(f".{candidate}"):
            ext = "jpg" if candidate == "jpeg" else candidate
            break

    folder = str(attribute_value_external_id)

    def _load() -> bytes:
        return gcs.download_bytes(object_name)

    try:
        return dropbox.ensure_shared_url(
            relative_dir=folder,
            filename=f"image.{ext}",
            load_bytes=_load,
        )
    except (GcsError, DropboxError) as exc:
        logger.warning(
            "Content export Dropbox ensure failed attribute_value=%s: %s",
            attribute_value_external_id,
            exc,
        )
        return None


def _business_sku_id(sku: SkuMaster | None, fallback: str = "") -> str:
    if sku is None:
        return fallback
    raw = (sku.attributes or {}).get("SKU")
    return str(raw) if raw else fallback


def _display_name(sku: SkuMaster | None, business_sku_id: str) -> str | None:
    if sku is None:
        return business_sku_id or None
    attrs = sku.attributes or {}
    for key in ("title", "name", "product_name"):
        value = attrs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return business_sku_id or None
