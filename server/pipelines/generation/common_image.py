"""Compress full Brand DNA once per image job into a minimal JSON DNA.

Two versions exist in the image pipeline: the complete Brand DNA document, and this
JSON (fonts, colors). Compression runs upstream only — never per slot.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from core.clients.openrouter import OpenRouterClient
from core.config import settings
from pipelines.generation import tools

logger = logging.getLogger(__name__)

JSON_DNA_MARKER = "JSON DNA"

_COMPRESS_MAX_TOKENS = 500

_FONT_KEYS = ("headline", "body", "dimension")
_COLOR_KEYS = ("primary", "secondary")


def extract(
    client: OpenRouterClient,
    brand_dna: str,
    *,
    session_id: str | None = None,
) -> str:
    """Return minimal JSON DNA (fonts, colors) reused for every image in this job."""
    source = brand_dna.strip()
    if not source:
        fallback = _fallback("")
        return _dumps(fallback) if fallback else ""

    prompt = _compress_prompt(source)
    try:
        parsed = client.call_tool(
            prompt,
            model=settings.openrouter_text_model,
            tool=tools.COMPRESSED_BRAND_DNA_TOOL,
            max_tokens=_COMPRESS_MAX_TOKENS,
            session_id=session_id,
        )
        dna = _normalize_dna(parsed if isinstance(parsed, dict) else {})
        if dna:
            return _dumps(dna)
        logger.warning("Compressed Brand DNA missing styling fields; using fallback")
    except Exception:  # noqa: BLE001 — fallback keeps the job running
        logger.exception("Brand DNA compression failed; using fallback")

    fallback = _fallback(source)
    return _dumps(fallback) if fallback else ""


def format_block(compressed: str | None) -> str:
    """JSON DNA block passed into the per-slot planner."""
    text = (compressed or "").strip()
    if not text:
        return ""
    return (
        f"{JSON_DNA_MARKER} (brand styling). Match these fonts and colors "
        "for overlays and UI chrome. Do not recolor the product. Do not paint "
        "typeface names or hex codes as text on the artwork.\n"
        f"{text}"
    )


def append_to_prompt(scene: str, compressed: str | None) -> str:
    """Join the slot-specific scene with the job-wide JSON DNA."""
    scene_text = scene.strip()
    block = format_block(compressed)
    if not block:
        return scene_text
    if not scene_text:
        return block
    return f"{scene_text}\n\n{block}"


def _compress_prompt(brand_dna: str) -> str:
    return (
        "Extract a minimal JSON DNA of this brand's visual styling for an image "
        "generator. The same JSON is reused for every image in this catalog job.\n"
        "\n"
        "Copy ONLY what the source names. Do not invent fonts or hex codes.\n"
        "Keep it small:\n"
        "- fonts.headline / fonts.body / fonts.dimension: typeface names as written "
        "(drop the usage essay after the name).\n"
        "- colors.primary / colors.secondary: the named brand palette.\n"
        "\n"
        "Do not include banned colors, moods, photography style, or avoid lists.\n"
        "\n"
        "Skip audience essays, copy voice, logos/wordmarks, lifestyle concept pools, "
        "INFOGRAPHIC RULES, callout counts, panel layouts, and selling_angle_priorities.\n"
        "\n"
        "When finished, call the submit_compressed_brand_dna tool.\n"
        "\n"
        "=== BRAND DNA (source) ===\n"
        f"{brand_dna}"
    )


def _normalize_dna(parsed: dict[str, Any]) -> dict[str, Any]:
    fonts_in = parsed.get("fonts") if isinstance(parsed.get("fonts"), dict) else {}
    colors_in = parsed.get("colors") if isinstance(parsed.get("colors"), dict) else {}

    fonts = {key: value for key in _FONT_KEYS if (value := _clean_str(fonts_in.get(key)))}
    colors: dict[str, list[str]] = {}
    for key in _COLOR_KEYS:
        items = _clean_str_list(colors_in.get(key))
        if items:
            colors[key] = items

    out: dict[str, Any] = {}
    if fonts:
        out["fonts"] = fonts
    if colors:
        out["colors"] = colors
    return out


def _dumps(dna: dict[str, Any]) -> str:
    return json.dumps(dna, ensure_ascii=False, indent=2)


def _clean_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _clean_str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return _split_list(value)
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def _fallback(brand_dna: str) -> dict[str, Any]:
    fonts: dict[str, str] = {}
    headline = _font_name(
        _field(brand_dna, "primary_font") or _field(brand_dna, "headline_font")
    )
    body = _font_name(_field(brand_dna, "secondary_font") or _field(brand_dna, "body_font"))
    dimension = _font_name(_field(brand_dna, "dimension_font"))
    if headline:
        fonts["headline"] = headline
    if body:
        fonts["body"] = body
    if dimension:
        fonts["dimension"] = dimension

    colors: dict[str, list[str]] = {}
    primary = _list_field(brand_dna, "brand_colors_primary")
    secondary = _list_field(brand_dna, "brand_colors_secondary")
    if primary:
        colors["primary"] = primary
    if secondary:
        colors["secondary"] = secondary

    out: dict[str, Any] = {}
    if fonts:
        out["fonts"] = fonts
    if colors:
        out["colors"] = colors
    return out


def _font_name(raw: str | None) -> str | None:
    if not raw:
        return None
    name = raw.split(" - ", 1)[0].split(" — ", 1)[0].strip()
    return name or None


def _list_field(brand_dna: str, key: str) -> list[str]:
    raw = _field(brand_dna, key)
    if not raw:
        return []
    return _split_list(raw)


def _split_list(raw: str) -> list[str]:
    inner = raw.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]
    return [part.strip() for part in inner.split(",") if part.strip()]


def _field(brand_dna: str, key: str) -> str | None:
    """Pull a markdown ``**key**: value`` line from freeform Brand DNA."""
    match = re.search(
        rf"\*\*{re.escape(key)}\*\*:\s*(.+)$",
        brand_dna,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not match:
        return None
    return match.group(1).strip() or None
