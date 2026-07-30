import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.config import settings
from core.exceptions import GenerateInputError, ProductNotFoundError

_LOGO_URL_RE = re.compile(
    r"\*\*brand_logo_primary\*\*:\s*(https?://\S+)",
    re.IGNORECASE,
)


def _input_root() -> Path:
    root = Path(settings.generate_input_dir)
    if not root.is_absolute():
        root = Path.cwd() / root
    return root


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise GenerateInputError(f"Missing generate input file: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise GenerateInputError(f"Expected JSON object in {path}")
    return data


@lru_cache(maxsize=1)
def load_brand_dna() -> str:
    path = Path.cwd() / "cortina_brand_dna.md"
    if not path.exists():
        raise GenerateInputError(f"Brand DNA file not found: {path}")
    return path.read_text(encoding="utf-8")


def extract_brand_logo_url(brand_dna: str | None = None) -> str | None:
    """Parse brand_logo_primary URL from Brand DNA markdown."""
    text = brand_dna if brand_dna is not None else load_brand_dna()
    match = _LOGO_URL_RE.search(text)
    if not match:
        return None
    return match.group(1).rstrip(")")


@lru_cache(maxsize=1)
def load_channel_rules() -> dict[str, Any]:
    return _read_json(_input_root() / "channel" / "curtains_amazon_v1.json")


@lru_cache(maxsize=1)
def load_text_prompt_contract() -> dict[str, Any]:
    return _read_json(_input_root() / "prompts" / "text_batch_v1.json")


@lru_cache(maxsize=1)
def load_image_prompt_contract() -> dict[str, Any]:
    return _read_json(_input_root() / "prompts" / "image_one_by_one_v1.json")


@lru_cache(maxsize=1)
def load_image_brief_contract() -> dict[str, Any]:
    return _read_json(_input_root() / "prompts" / "image_brief_json_v1.json")


@lru_cache(maxsize=1)
def load_overlay_visual_intelligence() -> dict[str, Any]:
    return _read_json(_input_root() / "intelligence" / "overlay_visual_v1.json")


@lru_cache(maxsize=1)
def load_creative_concepts() -> dict[str, Any]:
    return _read_json(_input_root() / "intelligence" / "creative_concepts_v1.json")


def resolve_creative_angle(
    creative_concepts: dict[str, Any],
    *,
    image_type: str,
    variant: int,
) -> dict[str, str]:
    """Map hero/infographic/lifestyle/a_plus + variant → LOAI-style angle name/text."""
    type_map = {
        "hero": "image_concept_main",
        "infographic": "image_concept_infographic",
        "lifestyle": "image_concept_lifestyle",
        "a_plus": "a_plus_content",
    }
    concept_key = type_map.get(image_type, image_type)
    concept_types = creative_concepts.get("concept_types") or {}
    block = concept_types.get(concept_key) if isinstance(concept_types, dict) else None
    angles = (block or {}).get("creative_angles") if isinstance(block, dict) else None
    if isinstance(angles, list):
        for item in angles:
            if isinstance(item, dict) and int(item.get("variant") or 0) == variant:
                return {
                    "creative_angle_name": str(item.get("name") or f"{image_type}_v{variant}"),
                    "concept_angle": str(item.get("angle") or ""),
                }
    return {
        "creative_angle_name": f"{image_type}_v{variant}",
        "concept_angle": "",
    }


@lru_cache(maxsize=1)
def load_pim_products() -> dict[str, dict[str, Any]]:
    payload = _read_json(_input_root() / "pim" / "cortina_curtains_products_5.json")
    products = payload.get("products")
    if not isinstance(products, list):
        raise GenerateInputError("PIM file missing products list")

    by_key: dict[str, dict[str, Any]] = {}
    for product in products:
        if not isinstance(product, dict):
            continue
        key = product.get("product_key")
        if isinstance(key, str) and key:
            by_key[key] = product
    if not by_key:
        raise GenerateInputError("PIM file has no usable product_key values")
    return by_key


@lru_cache(maxsize=1)
def load_manifest_product_keys() -> list[str]:
    payload = _read_json(_input_root() / "manifests" / "cortina_curtains_run_001_5_skus.json")
    keys = payload.get("product_keys")
    if not isinstance(keys, list) or not keys:
        raise GenerateInputError("Manifest missing product_keys")
    return [str(key) for key in keys]


def get_product(product_key: str) -> dict[str, Any]:
    product = load_pim_products().get(product_key)
    if product is None:
        raise ProductNotFoundError(product_key)
    return product


def build_sku_context(product: dict[str, Any]) -> dict[str, Any]:
    """Viable fields for marketplace generation. Description falls back to product_name.

    Do not pass carton/package LBH or case-pack counts as curtain retail facts.
    Today's master often stores package dims (e.g. 25cm) and case pack (e.g. 8),
    which caused title hallucinations like "25 cm length" / "26 feet".
    """
    product_name = product.get("product_name")
    description = product.get("description") or product_name
    attrs = product.get("attributes_optional") or {}
    context: dict[str, Any] = {
        "product_key": product.get("product_key"),
        "brand": product.get("brand"),
        "product_name": product_name,
        "description": description,
        "primary_image_url": (product.get("source_assets") or {}).get("primary_image_url"),
        "color": attrs.get("color"),
        "material": attrs.get("material"),
        "fact_source_priority": [
            "product_name",
            "description",
            "color",
            "material",
            "primary_image_url (visual only; do not invent sizes from it)",
        ],
        "do_not_invent": [
            "curtain drop/length in cm or feet",
            "width/height",
            "fabric care / machine wash",
            "eyelet vs rod-pocket unless stated",
            "thermal / noise / UV claims unless stated",
        ],
    }
    # Only include color/material when present; omit null noise.
    if not context["color"]:
        context.pop("color")
    if not context["material"]:
        context.pop("material")
    return context


def build_image_reference_urls(
    *,
    brand_dna: str,
    sku_context: dict[str, Any],
) -> list[str]:
    """Raw product photo only. Official logo is stamped after generation."""
    del brand_dna  # logo URL is used by stamp step, not image-model refs
    refs: list[str] = []
    primary = sku_context.get("primary_image_url")
    if isinstance(primary, str) and primary.strip():
        refs.append(primary.strip())
    return refs
