"""Assemble generation context from catalog DB + GCS product images.

Product facts come from ``sku_master.attributes`` (all keys, as-is). Brand DNA and
category intelligence come from ``brand`` / ``category_intelligence``. Reference photos
are listed under ``products/{sku_id}/assets/images/`` in GCS and exposed as signed GET URLs
for the model.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from core.clients.gcs import GcsClient
from core.exceptions import (
    BrandDnaMissingError,
    BrandNotFoundError,
    CategoryIntelligenceMissingError,
    GcsError,
    ProductNotFoundError,
)
from entities.catalog.sku_master import SkuMaster
from pipelines.generation.context import GenerationContext
from repositories.catalog import brand as brand_repo
from repositories.catalog import category_intelligence as category_intelligence_repo
from repositories.catalog import category_marketplace as category_marketplace_repo
from utils import flatfile as flatfile_utils

# Signed GET URLs must outlive the OpenRouter round-trip for this execute call.
_REFERENCE_IMAGE_URL_TTL_SECONDS = 3600


def load_context(
    session: Session,
    gcs: GcsClient,
    *,
    sku: SkuMaster,
    brand_id: int,
    marketplace_id: int,
) -> GenerationContext:
    """Assemble generation context for a brand × SKU × marketplace."""
    if sku.deleted_at is not None:
        raise ProductNotFoundError(f"No live SKU for id={sku.id}")

    product = _product_from_sku(sku)
    business_sku_id = str(product["SKU"])

    return GenerationContext(
        product=product,
        category_intelligence=_load_category_intelligence(
            session,
            marketplace_id=marketplace_id,
            category_id=sku.category_id,
        ),
        brand_dna=_load_brand_dna(session, brand_id),
        product_image_urls=_product_reference_image_urls(gcs, business_sku_id),
    )


def _product_from_sku(sku: SkuMaster) -> dict[str, Any]:
    """Return every attribute on the SKU as the product payload (no field filtering)."""
    attributes = dict(sku.attributes or {})
    business_sku_id = str(attributes.get("SKU") or "").strip()
    if not business_sku_id:
        raise ProductNotFoundError(f"SKU id={sku.id} is missing attributes.SKU")
    return attributes


def _load_brand_dna(session: Session, brand_id: int) -> str:
    brand = brand_repo.get_by_id(session, brand_id)
    if brand is None:
        raise BrandNotFoundError(f"brand_id={brand_id}")
    dna = (brand.brand_dna or "").strip()
    if not dna:
        raise BrandDnaMissingError(f"brand_id={brand_id} has empty brand_dna")
    return dna


def _load_category_intelligence(
    session: Session,
    *,
    marketplace_id: int,
    category_id: int,
) -> dict[str, Any]:
    junction = category_marketplace_repo.get_by_marketplace_and_category(
        session,
        marketplace_id,
        category_id,
    )
    if junction is None:
        raise CategoryIntelligenceMissingError(
            f"No category_marketplace row for marketplace_id={marketplace_id} "
            f"category_id={category_id}"
        )
    row = category_intelligence_repo.get_by_category_marketplace_id(session, junction.id)
    if row is None:
        raise CategoryIntelligenceMissingError(
            f"No category_intelligence row for category_marketplace id={junction.id}"
        )
    intelligence = row.intelligence
    if not isinstance(intelligence, dict) or not intelligence:
        raise CategoryIntelligenceMissingError(
            f"category_intelligence id={row.id} has empty intelligence"
        )
    return intelligence


def _product_reference_image_urls(gcs: GcsClient, business_sku_id: str) -> list[str]:
    """List GCS product images and return time-limited HTTPS GET URLs for the model."""
    prefix = flatfile_utils.product_image_prefix(business_sku_id)
    try:
        object_names = gcs.list_object_names(prefix)
    except GcsError:
        return []

    urls: list[str] = []
    for object_name in sorted(object_names):
        try:
            urls.append(
                gcs.signed_url(
                    object_name,
                    expiration_seconds=_REFERENCE_IMAGE_URL_TTL_SECONDS,
                )
            )
        except GcsError:
            continue
    return urls
