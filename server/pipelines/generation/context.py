"""Shared value object carrying everything a generation step reasons over.

``product`` (``sku_master.attributes`` intersected with the category allowed list) is the
authoritative fact sheet for text generation. ``category_intelligence`` supplies per-field
craft topics and ``backend_keywords`` candidates. ``brand_dna`` is loaded for image jobs
only — compressed to fonts/colors for slot briefs. ``product_image_urls`` are signed GCS
HTTPS URLs for the SKU's source photos.
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
