"""One vision call per SKU: observe photos, do not judge the CSV."""

from __future__ import annotations

import base64
from io import BytesIO
from typing import Any

from PIL import Image

from core.clients.openrouter import OpenRouterClient
from pipelines.inbound_qc.category import CATEGORY_BEDSHEET
from pipelines.inbound_qc.tools import extract_tool
from pipelines.inbound_qc.types import (
    BEDSHEET_TYPE_SCORE_KEYS,
    Checklist,
    Evidence,
    ExtractField,
    ExtractResult,
    ImageRef,
    ItemCounts,
    SkuBundle,
    Visibility,
    pick_product_type,
)
from utils.srgb_jpeg import JPEG_CONTENT_TYPE, convert_to_srgb_jpeg, needs_srgb_jpeg_convert

_EXTRACT_MAX_TOKENS = 4000
_EXTRACT_TIMEOUT_S = 180.0
_VISION_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_VISION_MAX_EDGE = 2048
_VISION_MAX_BYTES = 3_500_000


def _parse_visibility(raw: str) -> Visibility:
    if raw == "clear" or raw == "inferred" or raw == "not_visible":
        return raw
    return "not_visible"


def _parse_evidence(raw: str) -> Evidence:
    if raw == "on_product" or raw == "room_context" or raw == "none":
        return raw
    return "none"


def _encode_rgb_jpeg(content: bytes) -> bytes:
    with Image.open(BytesIO(content)) as image:
        rgb = image.convert("RGB")
        buffer = BytesIO()
        rgb.save(buffer, format="JPEG", quality=95)
        return buffer.getvalue()


def _fit_vision(content: bytes, content_type: str) -> tuple[bytes, str]:
    if content_type in _VISION_TYPES and content_type != JPEG_CONTENT_TYPE:
        if len(content) <= _VISION_MAX_BYTES:
            return content, content_type
        content = _encode_rgb_jpeg(content)
        content_type = JPEG_CONTENT_TYPE
    if content_type != JPEG_CONTENT_TYPE:
        return content, content_type
    if len(content) <= _VISION_MAX_BYTES:
        with Image.open(BytesIO(content)) as image:
            if max(image.size) <= _VISION_MAX_EDGE:
                return content, content_type
    with Image.open(BytesIO(content)) as image:
        rgb = image.convert("RGB")
        longest = max(rgb.size)
        if longest > _VISION_MAX_EDGE:
            scale = _VISION_MAX_EDGE / longest
            rgb = rgb.resize(
                (max(1, int(rgb.width * scale)), max(1, int(rgb.height * scale))),
                Image.Resampling.LANCZOS,
            )
        buffer = BytesIO()
        rgb.save(buffer, format="JPEG", quality=95, optimize=True)
        return buffer.getvalue(), JPEG_CONTENT_TYPE


def _for_vision(content: bytes, content_type: str) -> tuple[bytes, str]:
    """Print TIFF/CMYK JPEG → sRGB JPEG (same rules as wizard upload), then fit the model."""
    if needs_srgb_jpeg_convert(content):
        content = convert_to_srgb_jpeg(content)
        content_type = JPEG_CONTENT_TYPE
    elif content_type not in _VISION_TYPES:
        content = _encode_rgb_jpeg(content)
        content_type = JPEG_CONTENT_TYPE
    return _fit_vision(content, content_type)


def _data_url(image: ImageRef) -> str | None:
    if image.url:
        return image.url
    if not image.content:
        return None
    content, content_type = _for_vision(image.content, image.content_type)
    encoded = base64.standard_b64encode(content).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def _clip(text: object, limit: int) -> str:
    value = str(text or "").strip()
    return value[:limit]


def _clamp_confidence(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return 0
    return max(0, min(100, int(round(float(raw)))))


def _parse_field(raw: Any) -> ExtractField | None:
    if not isinstance(raw, dict):
        return None
    name = _clip(raw.get("name"), 40).lower()
    if name == "ocr":
        return None
    if name == "bed_size":
        name = "size"
    if name == "colour":
        name = "color"
    if not name:
        return None
    visibility = _parse_visibility(_clip(raw.get("visibility"), 20).lower())
    evidence = _parse_evidence(_clip(raw.get("evidence"), 20).lower())
    images_raw = raw.get("images")
    image_names: tuple[str, ...] = ()
    if isinstance(images_raw, list):
        image_names = tuple(_clip(item, 120) for item in images_raw if str(item).strip())
    return ExtractField(
        name=name,
        observed=_clip(raw.get("observed"), 400),
        visibility=visibility,
        confidence=_clamp_confidence(raw.get("confidence")),
        evidence=evidence,
        family=_clip(raw.get("family"), 40).lower(),
        images=image_names,
    )


def _parse_counts(raw: Any) -> ItemCounts:
    if not isinstance(raw, dict):
        return ItemCounts()

    def _opt_int(key: str) -> int | None:
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return max(0, int(value))

    return ItemCounts(
        total_visible=_opt_int("total_visible"),
    )


def _parse_type_scores(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    if not any(key in raw for key in BEDSHEET_TYPE_SCORE_KEYS):
        return {}
    return {key: _clamp_confidence(raw.get(key)) for key in BEDSHEET_TYPE_SCORE_KEYS}


def _apply_type_scores(fields: list[ExtractField], scores: dict[str, int]) -> list[ExtractField]:
    picked = pick_product_type(scores)
    if picked is None:
        return fields
    winner, score = picked
    display = winner.replace("_", " ")
    existing = next((item for item in fields if item.name == "product_type"), None)
    replacement = ExtractField(
        name="product_type",
        observed=display,
        visibility="clear",
        confidence=score,
        evidence=existing.evidence if existing is not None else "on_product",
        family=winner,
        images=existing.images if existing is not None else (),
    )
    others = [item for item in fields if item.name != "product_type"]
    return [replacement, *others]


def parse_extract_payload(parsed: dict[str, Any]) -> ExtractResult:
    fields_raw = parsed.get("fields")
    fields: list[ExtractField] = []
    if isinstance(fields_raw, list):
        for item in fields_raw:
            field = _parse_field(item)
            if field is not None:
                fields.append(field)
    scores = _parse_type_scores(parsed.get("product_type_scores"))
    if scores:
        fields = _apply_type_scores(fields, scores)
    images_agree = parsed.get("images_agree")
    return ExtractResult(
        fields=tuple(fields),
        images_agree=images_agree is not False,
        item_counts=_parse_counts(parsed.get("item_counts")),
        product_type_scores=scores,
    )


def _image_labels(bundle: SkuBundle) -> str:
    labels = [f"Image {index + 1} is {image.filename}" for index, image in enumerate(bundle.images)]
    return " ".join(labels)


def _no_ocr_rules() -> str:
    return (
        "Do not OCR. Do not transcribe SKUs, care labels, barcodes, or other on-image text. "
        "Use printed size or color only when it is clearly the product fact, not a code. "
        "Do not assume catalog values. Do not mention a spreadsheet.\n"
    )


def _generic_extract_prompt(bundle: SkuBundle, checklist: Checklist) -> str:
    visual = ", ".join(checklist.visual) or "color, pattern, size, item_count, material"
    return (
        "You are catalog intake QA. Look only at the product photos.\n"
        "Do not assume the product category. "
        + _no_ocr_rules()
        + f"Identify what the photos show, then fill extract fields for: {visual}.\n"
        "Use visibility not_visible when that fact is not visible on the photos.\n"
        "For size, infer a standard size from the product in the photo when you can "
        "(visibility inferred). Use clear only if a label or pack prints it. "
        "Use not_visible only if you cannot tell at all.\n"
        "For material, only if the surface or a label makes it clear.\n"
        "For item_count, count distinct sellable pieces of this product, not props.\n"
        "images_agree is false only when the photos look like different product variants "
        "(different colourway, model, or pack).\n"
        "Lifestyle vs packshot of the same product still agrees.\n" + _image_labels(bundle)
    )


def _bedsheet_extract_prompt(bundle: SkuBundle, checklist: Checklist) -> str:
    core = ("product_type", "color", "pattern", "size")
    remaining = [name for name in checklist.visual if name not in core]
    rest = ", ".join(remaining) if remaining else "none"
    return (
        "You are catalog intake QA. The catalog lists this as a bedsheet. "
        "Look only at the product photos.\n"
        + _no_ocr_rules()
        + "Fill product_type_scores first, then the extract fields.\n"
        "Score each covering independently from the photos, 0–100. "
        "Do not make the scores sum to 100. Do not copy the catalog type.\n"
        "A thin flat or fitted sheet, or a sheet set, is high bedsheet and near-zero "
        "duvet, comforter, quilt, blanket, and duvet_cover.\n"
        "A puffy, quilted, or filled covering (visible loft) is high duvet or comforter "
        "and low bedsheet. Score quilt, blanket, and duvet_cover only when that is "
        "what the photos show.\n"
        "Fill extract fields in this order:\n"
        "1. product_type — short label that matches your highest score. "
        "Visibility and images still come from the photos.\n"
        "2. color — dominant colour of the sheet itself, not the room.\n"
        "3. pattern — print or solid, as visible on the sheet.\n"
        "4. size — infer Single/Double/Queen/King from the bed and how the sheet sits. "
        "Use visibility inferred when you read it from the scene; clear if a label or pack "
        "prints it. Use not_visible only if you cannot tell at all.\n"
        f"5. Remaining attributes visible on the photos: {rest}. "
        "Use not_visible when a remaining field is not in the photos.\n"
        "images_agree is false only when the photos look like different product variants "
        "(different colourway, model, or pack).\n"
        "Lifestyle vs packshot of the same product still agrees.\n" + _image_labels(bundle)
    )


def extract_prompt(bundle: SkuBundle, checklist: Checklist) -> str:
    if checklist.category == CATEGORY_BEDSHEET:
        return _bedsheet_extract_prompt(bundle, checklist)
    return _generic_extract_prompt(bundle, checklist)


def extract_sku(
    client: OpenRouterClient,
    bundle: SkuBundle,
    checklist: Checklist,
    *,
    model: str,
) -> ExtractResult:
    urls = [url for url in (_data_url(image) for image in bundle.images) if url]
    if not urls:
        return ExtractResult(images_agree=True)

    parsed = client.call_tool(
        extract_prompt(bundle, checklist),
        model=model,
        tool=extract_tool(checklist),
        image_urls=urls,
        max_tokens=_EXTRACT_MAX_TOKENS,
        timeout=_EXTRACT_TIMEOUT_S,
    )
    if not isinstance(parsed, dict):
        raise ValueError("inbound QC extract returned a non-object")
    return parse_extract_payload(parsed)
