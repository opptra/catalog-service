"""SKU image download — signed URLs for client-side zip assembly."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.orm import Session

from core.clients.gcs import GcsClient
from core.exceptions import JobNotFoundError, SkuNotFoundError
from entities.catalog.attribute_enums import AttributeName
from repositories.catalog import attribute_master as attribute_master_repo
from repositories.catalog import job as job_repo
from repositories.catalog import marketplace as marketplace_repo
from repositories.catalog import sku_generation_job as sku_generation_job_repo
from repositories.catalog import sku_marketplace_attribute_value as attribute_value_repo
from repositories.catalog import sku_master as sku_master_repo

logger = logging.getLogger(__name__)

_SIGNED_URL_TTL_SECONDS = 3600

_FOLDER_BY_ATTRIBUTE: dict[AttributeName, str] = {
    AttributeName.IMAGE: "pdp_images",
    AttributeName.A_PLUS: "a_plus_images",
}


def resolve_job_in_group(
    session: Session,
    job_group_id: UUID,
    marketplace_external_id: UUID,
):
    """Return the generation job for ``job_group_id`` + marketplace."""
    marketplace = marketplace_repo.get_by_external_id(session, marketplace_external_id)
    if marketplace is None:
        raise JobNotFoundError(f"marketplace not found: {marketplace_external_id}")

    members = list(job_repo.list_group_members(session, job_group_id))
    for job in members:
        if job.marketplace_id == marketplace.id:
            return job, marketplace
    raise JobNotFoundError(
        f"no job in group {job_group_id} for marketplace {marketplace_external_id}"
    )


def list_sku_image_urls(
    session: Session,
    gcs: GcsClient,
    *,
    job_group_id: UUID,
    sku_id: str,
    marketplace_external_id: UUID,
) -> dict:
    """Signed URLs for latest IMAGE / A_PLUS values for one SKU × marketplace."""
    job, marketplace = resolve_job_in_group(session, job_group_id, marketplace_external_id)

    sku = sku_master_repo.get_live_by_attribute_sku_id(session, sku_id)
    if sku is None:
        raise SkuNotFoundError(f"Unknown or deleted sku_id: {sku_id}")

    sku_jobs = list(sku_generation_job_repo.list_by_job_id(session, job.id))
    sku_job = next((row for row in sku_jobs if row.sku_id == sku.id), None)
    if sku_job is None:
        raise SkuNotFoundError(f"SKU {sku_id} is not on this job group")

    values = list(attribute_value_repo.list_latest_by_sku_generation_job_id(session, sku_job.id))
    if not values:
        raise JobNotFoundError(f"No generated images for SKU {sku_id}")

    attribute_ids = {row.attribute_id for row in values}
    masters = {
        master.id: master
        for master in attribute_master_repo.list_by_ids(session, list(attribute_ids))
    }

    images: list[dict] = []
    for row in sorted(values, key=lambda item: (item.attribute_id, item.slot)):
        master = masters.get(row.attribute_id)
        if master is None:
            continue
        try:
            name = AttributeName(master.name)
        except ValueError:
            continue
        folder = _FOLDER_BY_ATTRIBUTE.get(name)
        if folder is None:
            continue
        if not str(row.value).startswith("gs://"):
            continue
        object_name = gcs.object_name_from_gs_uri(row.value)
        if object_name is None:
            logger.warning("Skipping unreadable image URI for SKU %s: %s", sku_id, row.value)
            continue
        extension = _extension(object_name)
        images.append(
            {
                "folder": folder,
                "filename": f"{row.slot}{extension}",
                "url": gcs.signed_url_for_gs_uri(
                    row.value, expiration_seconds=_SIGNED_URL_TTL_SECONDS
                ),
            }
        )

    if not images:
        raise JobNotFoundError(f"No downloadable images for SKU {sku_id}")

    slug = marketplace.name.strip().lower().replace(" ", "-") or "marketplace"
    return {
        "sku_id": sku_id,
        "marketplace_name": marketplace.name,
        "filename": f"{sku_id}-{slug}-images.zip",
        "images": images,
    }


def _extension(object_name: str) -> str:
    if "." in object_name.rsplit("/", 1)[-1]:
        return "." + object_name.rsplit(".", 1)[-1].lower()
    return ".jpg"
