"""Shared value object carrying everything a generation step reasons over.

The three inputs play distinct roles: ``product`` is the authoritative source of facts,
``category_intelligence`` is guidance on how to optimize the listing, and ``brand_dna`` is
voice/guardrails. ``product_image_urls`` are reference images (remote or ``data:`` URLs) that
anchor generated images to the real product.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class GenerationContext:
    product: dict[str, Any]
    category_intelligence: dict[str, Any]
    brand_dna: str
    product_image_urls: list[str] = field(default_factory=list)
