"""Load the three local generation inputs and resolve the product for a SKU.

The database holds only metadata/status; the product content the pipeline generates from lives
in these files under ``server/input``. Product reference images are resolved to portable
``data:`` URLs so the image model can anchor to the real product.
"""

import re
from pathlib import Path
from typing import Any

from core.exceptions import CategoryIntelligenceMissingError, ProductNotFoundError
from generation.context import GenerationContext
from utils import files
from utils import images as image_utils

# server/generation/inputs.py -> parents[1] == server/
_INPUT_DIR = Path(__file__).resolve().parents[1] / "input"
_BRAND_DNA_FILE = _INPUT_DIR / "brand-dna.txt"
_CATEGORY_INTELLIGENCE_FILE = _INPUT_DIR / "category-intelligence.json"
_PRODUCT_DATA_FILE = _INPUT_DIR / "productdata.json"

_SKU_PREFIX_KEYS = ("product_key", "sku", "article_code")
_IMAGE_ASSET_KEYS = ("primary_image_url", "raw_image_link")
_BRAND_LOGO_PATTERN = re.compile(r"brand_logo_primary\**\s*:\s*(https?://\S+)")


def load_context(sku_id: int) -> GenerationContext:
    """Assemble the generation context (product facts + category intelligence + brand DNA)."""
    product = _find_product(sku_id)
    brand_dna = files.read_text(_BRAND_DNA_FILE)
    return GenerationContext(
        product=product,
        category_intelligence=_load_category_intelligence(),
        brand_dna=brand_dna,
        product_image_urls=_product_reference_images(product),
        brand_logo_url=_brand_logo_url(brand_dna),
    )


def _load_category_intelligence() -> dict[str, Any]:
    if not _CATEGORY_INTELLIGENCE_FILE.exists():
        raise CategoryIntelligenceMissingError(
            f"Category intelligence file not found: {_CATEGORY_INTELLIGENCE_FILE}"
        )
    if not files.read_text(_CATEGORY_INTELLIGENCE_FILE).strip():
        raise CategoryIntelligenceMissingError(
            f"Category intelligence file is empty: {_CATEGORY_INTELLIGENCE_FILE}"
        )
    return files.read_json(_CATEGORY_INTELLIGENCE_FILE)


def _find_product(sku_id: int) -> dict[str, Any]:
    """Match the integer ``sku_id`` to a product by the digits after the ``COR-`` prefix."""
    data = files.read_json(_PRODUCT_DATA_FILE)
    for product in data.get("products", []):
        for key in _SKU_PREFIX_KEYS:
            raw = product.get(key)
            if isinstance(raw, str):
                _, _, suffix = raw.partition("-")
                if suffix.isdigit() and int(suffix) == sku_id:
                    return product
    raise ProductNotFoundError(f"No product matches sku_id={sku_id} in the input product data")


def _product_reference_images(product: dict[str, Any]) -> list[str]:
    """Resolve the product's source images to data URLs (falling back to the raw URL)."""
    assets = product.get("source_assets") or {}
    references: list[str] = []
    for key in _IMAGE_ASSET_KEYS:
        url = assets.get(key)
        if isinstance(url, str) and url.strip():
            references.append(image_utils.to_data_url(url) or url)
    return references


def _brand_logo_url(brand_dna: str) -> str | None:
    """Extract the brand logo URL from the Brand DNA and resolve it to a data URL."""
    match = _BRAND_LOGO_PATTERN.search(brand_dna)
    if not match:
        return None
    url = match.group(1)
    return image_utils.to_data_url(url) or url
