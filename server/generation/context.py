"""Shared value object carrying everything a generation step reasons over.

The three inputs play distinct roles: ``product`` (``sku_master.attributes``) is the
authoritative source of facts, ``category_intelligence`` (from ``category_marketplace``)
is guidance on how to optimize the listing, and ``brand_dna`` (from ``brand.brand_dna``)
is voice/guardrails. ``product_image_urls`` are signed GCS HTTPS URLs for the SKU's
source photos under ``products/{sku_id}/assets/images/``.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class GenerationContext:
    product: dict[str, Any]
    category_intelligence: dict[str, Any]
    brand_dna: str
    product_image_urls: list[str] = field(default_factory=list)
