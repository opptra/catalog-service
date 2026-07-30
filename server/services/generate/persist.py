"""Persist generate outputs into the existing job / sku_job / attribute-value schema.

Requires seeded attribute_master rows (see migrations/generate_attributes_seed.sql)
and the `sku` table (migrations/001_sku.sql). Persistence is best-effort gated:
if required catalog rows are missing, we skip DB writes without failing generation.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.attribute_master import AttributeMaster
from entities.job import Job
from entities.job_attribute import JobAttribute
from entities.marketplace import Marketplace
from entities.sku_job import SkuJob
from entities.sku_marketplace_attribute_value import SkuMarketplaceAttributeValue
from entities.user import User
from repositories import sku as sku_repo

logger = logging.getLogger(__name__)

TEXT_ATTRIBUTES = ("title", "bullet_points", "item_highlights")
IMAGE_ATTRIBUTES = ("hero", "infographic", "lifestyle", "a_plus")


def _attr_by_name(session: Session) -> dict[str, AttributeMaster]:
    rows = session.scalars(select(AttributeMaster)).all()
    return {row.name: row for row in rows}


def _first_user_id(session: Session) -> int | None:
    return session.scalar(select(User.id).order_by(User.id.asc()).limit(1))


def _first_marketplace_id(session: Session) -> int | None:
    return session.scalar(select(Marketplace.id).order_by(Marketplace.id.asc()).limit(1))


def _next_version(
    session: Session,
    *,
    sku_id: int,
    marketplace_id: int,
    attribute_id: int,
    slot: int,
) -> int:
    current = session.scalar(
        select(SkuMarketplaceAttributeValue.version)
        .where(
            SkuMarketplaceAttributeValue.sku_id == sku_id,
            SkuMarketplaceAttributeValue.marketplace_id == marketplace_id,
            SkuMarketplaceAttributeValue.attribute_id == attribute_id,
            SkuMarketplaceAttributeValue.slot == slot,
        )
        .order_by(SkuMarketplaceAttributeValue.version.desc())
        .limit(1)
    )
    return int(current or 0) + 1


def _write_value(
    session: Session,
    *,
    sku_id: int,
    marketplace_id: int,
    attribute: AttributeMaster,
    slot: int,
    value: str,
    sku_job_id: int,
) -> None:
    version = _next_version(
        session,
        sku_id=sku_id,
        marketplace_id=marketplace_id,
        attribute_id=attribute.id,
        slot=slot,
    )
    session.add(
        SkuMarketplaceAttributeValue(
            external_id=uuid4(),
            sku_id=sku_id,
            marketplace_id=marketplace_id,
            attribute_id=attribute.id,
            slot=slot,
            version=version,
            value=value,
            sku_job_id=sku_job_id,
        )
    )


def persist_generate_job(
    session: Session,
    *,
    run_id: str,
    status: str,
    sku_results: list[Any],
    selected_images: dict[str, int],
    generate_text: bool,
    pim_by_key: dict[str, dict[str, Any]],
) -> UUID | None:
    """Write one generate run into job + sku_job + versioned attribute values.

    Returns job.external_id when persisted, else None.
    """
    attrs = _attr_by_name(session)
    required = set(TEXT_ATTRIBUTES if generate_text else ()) | set(selected_images)
    missing = [name for name in required if name not in attrs]
    if missing:
        logger.warning(
            "Skipping generate DB persist; missing attribute_master rows: %s",
            ", ".join(missing),
        )
        return None

    user_id = _first_user_id(session)
    marketplace_id = _first_marketplace_id(session)
    if user_id is None or marketplace_id is None:
        logger.warning("Skipping generate DB persist; users/marketplace not seeded")
        return None

    job = Job(
        created_by=user_id,
        marketplace_id=marketplace_id,
        status=status,
    )
    session.add(job)
    session.flush()

    # Quantities for image attributes (and text treated as qty 1).
    if generate_text:
        for name in TEXT_ATTRIBUTES:
            session.add(
                JobAttribute(
                    job_id=job.id,
                    attribute_id=attrs[name].id,
                    quantity=1,
                )
            )
    for image_type, qty in selected_images.items():
        session.add(
            JobAttribute(
                job_id=job.id,
                attribute_id=attrs[image_type].id,
                quantity=qty,
            )
        )

    for sku_result in sku_results:
        product_key = sku_result.product_key
        product = pim_by_key.get(product_key) or {}
        sku = sku_repo.get_or_create_by_product_key(
            session,
            product_key=product_key,
            name=str(product.get("product_name") or product_key),
            primary_image_url=((product.get("source_assets") or {}) or {}).get("primary_image_url"),
            pim_payload=product or None,
            status=str(product.get("status") or "draft"),
        )

        tasks: dict[str, Any] = {"run_id": run_id}
        if sku_result.text is not None:
            tasks["text"] = "done" if not sku_result.error else "error"
        for image in sku_result.images:
            tasks.setdefault(image.image_type, {})[str(image.variant)] = "done"
        if sku_result.error:
            tasks["error"] = sku_result.error

        sku_job = SkuJob(
            job_id=job.id,
            sku_id=sku.id,
            status="failed" if sku_result.error else "completed",
            tasks=tasks,
        )
        session.add(sku_job)
        session.flush()

        if sku_result.text is not None:
            _write_value(
                session,
                sku_id=sku.id,
                marketplace_id=marketplace_id,
                attribute=attrs["title"],
                slot=1,
                value=sku_result.text.title,
                sku_job_id=sku_job.id,
            )
            _write_value(
                session,
                sku_id=sku.id,
                marketplace_id=marketplace_id,
                attribute=attrs["bullet_points"],
                slot=1,
                value=json.dumps(sku_result.text.bullet_points),
                sku_job_id=sku_job.id,
            )
            _write_value(
                session,
                sku_id=sku.id,
                marketplace_id=marketplace_id,
                attribute=attrs["item_highlights"],
                slot=1,
                value=json.dumps(sku_result.text.item_highlights),
                sku_job_id=sku_job.id,
            )

        for image in sku_result.images:
            attr = attrs.get(image.image_type)
            if attr is None:
                continue
            _write_value(
                session,
                sku_id=sku.id,
                marketplace_id=marketplace_id,
                attribute=attr,
                slot=image.variant,
                value=image.relative_path,
                sku_job_id=sku_job.id,
            )

    session.commit()
    return job.external_id
