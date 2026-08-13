"""Shared value object carrying everything a generation step reasons over.

The three inputs play distinct roles: ``product`` (``sku_master.attributes``) is the
authoritative source of facts, ``category_intelligence`` (from the
``category_intelligence`` table) is guidance on how to optimize the listing, and
``brand_dna`` (from ``brand.brand_dna``) is voice/guardrails. ``product_image_urls``
are signed GCS HTTPS URLs for the SKU's source photos under
``products/{sku_id}/assets/images/``.

For image jobs, ``common_image_context`` holds a once-per-job distill of Brand DNA +
category visual norms (typography, palette, mood, on-image text rules) reused on every
plan/render/regenerate call — never a full DNA/CI dump.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class GenerationContext:
    product: dict[str, Any]
    category_intelligence: dict[str, Any]
    brand_dna: str
    product_image_urls: list[str] = field(default_factory=list)
    # Distilled once for image jobs: typography/palette/mood + category visual norms.
    # Never a dump of full Brand DNA or full Category Intelligence.
    common_image_context: dict[str, Any] | None = None
