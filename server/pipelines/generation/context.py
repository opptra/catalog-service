"""Shared value object carrying everything a generation step reasons over.

The three inputs play distinct roles: ``product`` (``sku_master.attributes``
intersected with the category allowed list) is the authoritative source of facts,
``category_intelligence`` (from the
``category_intelligence`` table) is guidance on how to optimize the listing, and
``brand_dna`` (from ``brand.brand_dna``) is voice/guardrails. ``product_image_urls``
are signed GCS HTTPS URLs for the SKU's source photos under
``products/{sku_id}/assets/images/``.

For image jobs, ``compressed_brand_dna`` is a minimal JSON DNA (fonts, colors)
compressed once from full Brand DNA and embedded in each assembled slot brief
sent to the image model. Product owns SKU color/pattern; DNA owns overlay
typefaces and brand chrome palette; category intelligence owns the slot recipe
(role, kind, content, pattern, feature claims). Font family names and hex codes
are look-to-match only and must never be printed on the artwork. Claim ownership
is capped upstream (``max_callouts``) from CI ``feature_priority`` ∩ verified
product facts before each slot brief is assembled.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class GenerationContext:
    product: dict[str, Any]
    category_intelligence: dict[str, Any]
    brand_dna: str
    product_image_urls: list[str] = field(default_factory=list)
    # Minimal JSON DNA compressed once per image job from full Brand DNA.
    compressed_brand_dna: str | None = None
