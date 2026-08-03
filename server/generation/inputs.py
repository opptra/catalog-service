"""Load the three local generation inputs and resolve the product for a SKU.

The database holds only metadata/status; the product content the pipeline generates from lives
in these files under ``server/input``. Product reference images are resolved to portable
``data:`` URLs so the image model can anchor to the real product.
"""

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


def load_context(sku_id: int) -> GenerationContext:
    """Assemble the generation context (product facts + category intelligence + brand DNA)."""
    product = _find_product(sku_id)
    brand_dna = files.read_text(_BRAND_DNA_FILE)
    return GenerationContext(
        product=product,
        category_intelligence=_load_category_intelligence(),
        brand_dna=brand_dna,
        product_image_urls=_product_reference_images(product),
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
    """Resolve every source image (an ordered array, not a fixed 1-2 keys) to data URLs.

    ``source_assets.images`` is the full set of real listing photos (main + every angle/closeup),
    in listing order — every one of them is passed to the model as a reference, not just the
    primary shot, so product fidelity doesn't rest on a single photo.
    """
    assets = product.get("source_assets") or {}
    images = assets.get("images")
    if not isinstance(images, list):
        return []
    references: list[str] = []
    for entry in images:
        url = entry.get("url") if isinstance(entry, dict) else entry
        if isinstance(url, str) and url.strip():
            references.append(image_utils.to_data_url(url) or url)
    return references
