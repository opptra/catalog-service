"""Extract and reuse a compact common image-context blob for every image call.

Built once per job from Brand DNA + category intelligence (image-relevant fields only).
Never dump full Brand DNA or full CI into plan/render/regenerate prompts.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from core.clients.openrouter import OpenRouterClient
from core.config import settings
from entities.catalog.attribute_enums import AttributeName
from pipelines.generation import category, tools
from pipelines.generation.context import GenerationContext

logger = logging.getLogger(__name__)

COMMON_IMAGE_CONTEXT_MARKER = "=== COMMON IMAGE CONTEXT ==="

_EXTRACT_MAX_TOKENS = 1200
_TYPE_ROLES = ("headline", "supporting", "dimension")
_PRODUCT_TRUE_GUARDRAIL = (
    "Never recolor the product to match the brand palette; product color, pattern, "
    "material, and shape are authoritative."
)
_CHROME_ONLY_GUARDRAIL = (
    "Brand colors apply only to image chrome (panels, badges, icon chips, headlines, "
    "captions, dividers), not to the product or every scene prop."
)


def extract(
    client: OpenRouterClient,
    ctx: GenerationContext,
    names: list[AttributeName],
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Build one common image-context JSON from Brand DNA + category CI.

    Prefer a structured LLM extract; fall back to a deterministic parse so image
    generation can still share palette/mood/category norms when the tool call fails.

    Typography is look-to-match (at most headline, supporting, dimension). Palette is
    chrome-only — never recolor the product. Never print font family names on the artwork.
    """
    source = category.image_brief(ctx.category_intelligence, names)
    try:
        parsed = client.call_tool(
            _extract_prompt(ctx.brand_dna, source),
            model=settings.openrouter_prompt_model,
            tool=tools.COMMON_IMAGE_CONTEXT_TOOL,
            max_tokens=_EXTRACT_MAX_TOKENS,
            session_id=session_id,
        )
        common = _normalize(parsed)
        if common.get("mood") or common.get("category"):
            return common
        logger.warning("Common image-context extract missing mood/category; using fallback")
    except Exception:  # noqa: BLE001 — fallback keeps the job running
        logger.exception("Common image-context extract failed; using fallback")
    return _fallback(ctx.brand_dna, source)


def format_block(common: dict[str, Any]) -> str:
    """Stable text block embedded in every image prompt."""
    has_type = isinstance(common.get("typography"), dict) and bool(common["typography"])
    type_line = (
        "Typography: match headline / supporting / dimension looks from this context on "
        "overlay slots (titles, callouts, size labels). Headline larger than supporting; "
        "dimension look only on measurement numbers. NEVER paint family names, "
        '"Font: …", or a specimen line on the artwork.'
        if has_type
        else (
            "Typography: DNA is silent on type — use clean, phone-readable sans and keep "
            "hierarchy via weight and size. NEVER paint font family names on the artwork."
        )
    )
    return (
        f"{COMMON_IMAGE_CONTEXT_MARKER}\n"
        f"{json.dumps(common, ensure_ascii=False, indent=2)}\n"
        "Product color, pattern, material, and shape are authoritative — never recolor or "
        "restyle the SKU to match the brand palette.\n"
        "Brand palette is for image chrome only (panels, badges, icon chips, headlines, "
        "captions, dividers) — not the product, and not every scene prop.\n"
        f"{type_line}"
    )


def ensure_in_prompt(prompt: str, common: dict[str, Any] | None) -> str:
    """Append or replace the common block so the prompt always carries the shared context."""
    if not common:
        return prompt
    block = format_block(common)
    stripped = prompt.strip()
    existing = extract_block_from_prompt(stripped)
    if existing is not None:
        start = stripped.find(COMMON_IMAGE_CONTEXT_MARKER)
        return f"{stripped[:start].rstrip()}\n\n{block}".strip()
    return f"{stripped}\n\n{block}".strip()


def extract_block_from_prompt(prompt: str) -> str | None:
    """Return the common-context section from a stored prompt, if present."""
    start = prompt.find(COMMON_IMAGE_CONTEXT_MARKER)
    if start < 0:
        return None
    return prompt[start:].strip() or None


def parse_common_from_prompt(prompt: str) -> dict[str, Any] | None:
    """Parse JSON after the marker from a stored prompt (for regenerate reuse)."""
    block = extract_block_from_prompt(prompt)
    if not block:
        return None
    body = block[len(COMMON_IMAGE_CONTEXT_MARKER) :].strip()
    # Drop trailing instruction sentence(s) after the JSON object.
    brace = body.find("{")
    if brace < 0:
        return None
    try:
        payload, _ = json.JSONDecoder().raw_decode(body[brace:])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return _normalize(payload)


def _extract_prompt(brand_dna: str, category_source: dict[str, Any]) -> str:
    return (
        "You extract a compact COMMON IMAGE CONTEXT used for EVERY image in one catalog job "
        "(gallery and enhanced-brand modules). Pull ONLY image-relevant details.\n\n"
        "From Brand DNA:\n"
        "- Palette for IMAGE CHROME only (panels, badges, icon chips, headlines, captions, "
        "dividers), with usage notes. NEVER apply brand colors to the product. Omit palette "
        "if DNA is silent on color.\n"
        "- Typography: at most three roles — headline (primary/heading), supporting "
        "(body/details), dimension (measurement face only if DNA names one). Ignore extra "
        "families (print-only, legal, wordmark, decorative fifth face). For each role: "
        "optional family as an art-direction hint plus a look (weight, serif vs sans, "
        "geometric vs humanist). Never instruct printing family names on the artwork. "
        "Omit typography if DNA is silent on fonts — do not invent families.\n"
        "- Banned type (script, cursive, brush, comic; serif headlines if DNA is sans-only) "
        "goes in visual_guardrails.\n"
        "- Short mood for the FRAME only. Do not rewrite the product scene from DNA if "
        "category + product already set it.\n"
        "- Visual do-nots (overcrowding, humans, neon, etc.).\n"
        "Always include visual_guardrails that the product must not be recolored and that "
        "brand colors are chrome-only. Do not include voice, copy essays, audience prose, "
        "logos/wordmarks, or font sizes in px/pt.\n\n"
        "From Category Intelligence: cross-slot visual norms for this category, on-image text "
        "density rules (phone-readable, minimal SEO-useful keywords, no fluff), shared product "
        "presentation cues. Do not copy per-slot shot briefs or long topic essays.\n\n"
        "Never invent brand colors or typefaces not supported by the sources. When finished, "
        "call the submit_common_image_context tool.\n\n"
        "=== BRAND DNA (source) ===\n"
        f"{brand_dna.strip()}\n\n"
        "=== CATEGORY INTELLIGENCE (image-relevant distill) ===\n"
        f"{json.dumps(category_source, ensure_ascii=False, indent=2)}"
    )


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    palette_raw = raw.get("palette") if isinstance(raw.get("palette"), dict) else {}
    category_raw = raw.get("category") if isinstance(raw.get("category"), dict) else {}

    palette = {
        key: value
        for key, value in {
            "primary": palette_raw.get("primary"),
            "secondary": palette_raw.get("secondary"),
            "accents": palette_raw.get("accents"),
            "notes": palette_raw.get("notes"),
        }.items()
        if value
    }

    category_out: dict[str, Any] = {}
    norms = category_raw.get("visual_norms")
    if isinstance(norms, list):
        category_out["visual_norms"] = [str(item).strip() for item in norms if str(item).strip()]
    on_image = str(category_raw.get("on_image_text") or "").strip()
    if on_image:
        category_out["on_image_text"] = on_image
    else:
        category_out["on_image_text"] = (
            "phone-readable; minimal SEO-useful keywords; no fluff; no internal jargon"
        )
    cues = category_raw.get("shared_product_cues")
    if isinstance(cues, list):
        category_out["shared_product_cues"] = [
            str(item).strip() for item in cues if str(item).strip()
        ]

    guardrails = raw.get("visual_guardrails")
    guardrail_list = (
        [str(item).strip() for item in guardrails if str(item).strip()]
        if isinstance(guardrails, list)
        else []
    )
    guardrail_list = _ensure_guardrail(guardrail_list, _PRODUCT_TRUE_GUARDRAIL)
    guardrail_list = _ensure_guardrail(guardrail_list, _CHROME_ONLY_GUARDRAIL)

    out: dict[str, Any] = {
        "mood": str(raw.get("mood") or "").strip() or "clean, catalog, consistent",
        "visual_guardrails": guardrail_list,
        "category": category_out,
    }
    if palette:
        out["palette"] = palette
    typography = _normalize_typography(raw.get("typography"))
    if typography:
        out["typography"] = typography
    return out


def _normalize_typography(raw: Any) -> dict[str, dict[str, str]] | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, dict[str, str]] = {}
    for role in _TYPE_ROLES:
        parsed = _type_role(raw.get(role))
        if parsed:
            out[role] = parsed
    return out or None


def _type_role(raw: Any) -> dict[str, str] | None:
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        return {"family": text, "look": text}
    if not isinstance(raw, dict):
        return None
    family = str(raw.get("family") or "").strip()
    look = str(raw.get("look") or "").strip()
    if not family and not look:
        return None
    role: dict[str, str] = {}
    if look:
        role["look"] = look
    elif family:
        role["look"] = f"match the look of {family}"
    if family:
        role["family"] = family
    return role


def _ensure_guardrail(items: list[str], line: str) -> list[str]:
    marker = line.split(";")[0].casefold()
    if any(marker in item.casefold() for item in items):
        return items
    return [*items, line]


def _fallback(brand_dna: str, category_source: dict[str, Any]) -> dict[str, Any]:
    mood = _field(brand_dna, "visual_mood") or _field(brand_dna, "photography_style") or "clean"
    primary_colors = _field(brand_dna, "brand_colors_primary")
    secondary_colors = _field(brand_dna, "brand_colors_secondary")

    category_name = category_source.get("category") or "this category"
    keywords = category_source.get("high_value_keywords") or []
    keyword_hint = ", ".join(str(k) for k in keywords[:8]) if keywords else ""

    plan = category_source.get("image_plan") or {}
    norms: list[str] = [
        f"Follow {category_name} marketplace visual norms from Category Intelligence.",
        "Honor COMMON IMAGE CONTEXT typography on overlay slots; heroes stay product-first.",
        "Product color is authoritative; brand palette is chrome only.",
    ]
    for track in plan.values() if isinstance(plan, dict) else []:
        if isinstance(track, dict) and track.get("build_rationale"):
            norms.append(str(track["build_rationale"]).strip()[:400])
            break

    cues: list[str] = []
    if keyword_hint:
        cues.append(f"Prefer SEO-useful on-image phrases when text is needed: {keyword_hint}")

    banned_type = _field(brand_dna, "banned_fonts") or _field(brand_dna, "banned_type")
    payload: dict[str, Any] = {
        "palette": {
            "primary": primary_colors,
            "secondary": secondary_colors,
            "notes": _field(brand_dna, "accent_color_rules"),
        },
        "mood": mood,
        "visual_guardrails": [g for g in [_field(brand_dna, "banned_colors"), banned_type] if g],
        "category": {
            "visual_norms": norms,
            "on_image_text": (
                "phone-readable; minimal SEO-useful keywords; no fluff; no internal jargon"
            ),
            "shared_product_cues": cues,
        },
    }
    typography = _fallback_typography(brand_dna)
    if typography:
        payload["typography"] = typography
    return _normalize(payload)


def _fallback_typography(brand_dna: str) -> dict[str, dict[str, str]] | None:
    return _normalize_typography(
        {
            "headline": (
                _field(brand_dna, "primary_font")
                or _field(brand_dna, "heading_font")
                or _field(brand_dna, "headline_font")
            ),
            "supporting": (
                _field(brand_dna, "secondary_font")
                or _field(brand_dna, "body_font")
                or _field(brand_dna, "supporting_font")
            ),
            "dimension": (
                _field(brand_dna, "measurement_font")
                or _field(brand_dna, "dimension_font")
                or _field(brand_dna, "measurements_font")
            ),
        }
    )


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
