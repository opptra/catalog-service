"""SKU image download — signed URLs for client-side zip assembly."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from core.clients.gcs import GcsClient
from core.exceptions import JobNotFoundError, SkuNotFoundError
from entities.catalog.attribute_enums import AttributeName
from entities.catalog.attribute_master import AttributeMaster
from entities.catalog.sku_marketplace_attribute_value import SkuMarketplaceAttributeValue
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
) -> dict[str, Any]:
    """Signed URLs for latest IMAGE / A_PLUS values for one SKU in the group."""
    members = list(job_repo.list_group_members(session, job_group_id))
    if not members:
        raise JobNotFoundError(f"Job group not found: {job_group_id}")

    sku = sku_master_repo.get_live_by_attribute_sku_id(session, sku_id)
    if sku is None:
        raise SkuNotFoundError(f"Unknown or deleted sku_id: {sku_id}")

    sku_jobs = [
        row
        for row in sku_generation_job_repo.list_by_job_ids(session, [job.id for job in members])
        if row.sku_id == sku.id
    ]
    if not sku_jobs:
        raise SkuNotFoundError(f"SKU {sku_id} is not on this job group")

    marketplace_ids = [job.marketplace_id for job in members if job.marketplace_id is not None]
    marketplace_by_id = {
        marketplace.id: marketplace
        for marketplace in marketplace_repo.list_by_ids(session, marketplace_ids)
    }
    job_by_id = {job.id: job for job in members}

    values_by_sku_job_id: dict[int, Sequence[SkuMarketplaceAttributeValue]] = {
        sku_job.id: attribute_value_repo.list_latest_by_sku_generation_job_id(session, sku_job.id)
        for sku_job in sku_jobs
    }
    attribute_ids = {row.attribute_id for values in values_by_sku_job_id.values() for row in values}
    masters = {
        master.id: master
        for master in attribute_master_repo.list_by_ids(session, list(attribute_ids))
    }

    images: list[dict[str, str]] = []
    for sku_job in sku_jobs:
        job = job_by_id.get(sku_job.job_id)
        if job is None or job.marketplace_id is None:
            continue
        marketplace = marketplace_by_id.get(job.marketplace_id)
        if marketplace is None:
            continue
        images.extend(
            _image_items(
                gcs,
                sku_id=sku_id,
                marketplace_folder=_marketplace_folder(marketplace.name),
                values=values_by_sku_job_id.get(sku_job.id, ()),
                masters=masters,
            )
        )

    images.sort(key=lambda item: (item["marketplace"], item["folder"], item["filename"]))
    if not images:
        raise JobNotFoundError(f"No downloadable images for SKU {sku_id}")

    return {
        "sku_id": sku_id,
        "filename": f"{sku_id}-images.zip",
        "images": images,
    }


def _image_items(
    gcs: GcsClient,
    *,
    sku_id: str,
    marketplace_folder: str,
    values: Sequence[SkuMarketplaceAttributeValue],
    masters: dict[int, AttributeMaster],
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
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
        items.append(
            {
                "marketplace": marketplace_folder,
                "folder": folder,
                "filename": f"{row.slot}{_extension(object_name)}",
                "url": gcs.signed_url_for_gs_uri(
                    row.value, expiration_seconds=_SIGNED_URL_TTL_SECONDS
                ),
            }
        )
    return items


def _marketplace_folder(name: str) -> str:
    text = name.strip() or "marketplace"
    return text.replace("/", "-").replace("\\", "-")


def _extension(object_name: str) -> str:
    if "." in object_name.rsplit("/", 1)[-1]:
        return "." + object_name.rsplit(".", 1)[-1].lower()
    return ".jpg"
