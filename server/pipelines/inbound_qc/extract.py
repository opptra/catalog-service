"""One vision call per SKU: observe photos, do not judge the CSV."""

from __future__ import annotations

import base64
from typing import Any

from core.clients.openrouter import OpenRouterClient
from pipelines.inbound_qc.category import CATEGORY_BEDSHEET
from pipelines.inbound_qc.tools import extract_tool
from pipelines.inbound_qc.types import (
    Checklist,
    Evidence,
    ExtractField,
    ExtractResult,
    ImageRef,
    ItemCounts,
    SkuBundle,
    Visibility,
)

_EXTRACT_MAX_TOKENS = 4000


def _parse_visibility(raw: str) -> Visibility:
    if raw == "clear" or raw == "inferred" or raw == "not_visible":
        return raw
    return "not_visible"


def _parse_evidence(raw: str) -> Evidence:
    if raw == "on_product" or raw == "room_context" or raw == "none":
        return raw
    return "none"


def _data_url(image: ImageRef) -> str | None:
    if image.url:
        return image.url
    if not image.content:
        return None
    encoded = base64.standard_b64encode(image.content).decode("ascii")
    return f"data:{image.content_type};base64,{encoded}"


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


def parse_extract_payload(parsed: dict[str, Any]) -> ExtractResult:
    fields_raw = parsed.get("fields")
    fields: list[ExtractField] = []
    if isinstance(fields_raw, list):
        for item in fields_raw:
            field = _parse_field(item)
            if field is not None:
                fields.append(field)
    images_agree = parsed.get("images_agree")
    return ExtractResult(
        fields=tuple(fields),
        images_agree=images_agree is not False,
        item_counts=_parse_counts(parsed.get("item_counts")),
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
        "You are catalog intake QA for a bedsheet SKU. Look only at the product photos.\n"
        + _no_ocr_rules()
        + "Fill extract fields in this order:\n"
        "1. product_type — is this a bedsheet (flat or fitted), or something else "
        "(duvet, comforter, quilt, duvet cover, blanket)? "
        "If it is not a bedsheet, say what it is in observed. "
        "A bedsheet set is still a bedsheet.\n"
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
    )
    if not isinstance(parsed, dict):
        raise ValueError("inbound QC extract returned a non-object")
    return parse_extract_payload(parsed)
