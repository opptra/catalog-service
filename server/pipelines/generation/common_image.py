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


def extract(
    client: OpenRouterClient,
    ctx: GenerationContext,
    names: list[AttributeName],
) -> dict[str, Any]:
    """Build one common image-context JSON from Brand DNA + category CI.

    Prefer a structured LLM extract; fall back to a deterministic parse so image
    generation can still share typography/palette when the tool call fails.
    """
    source = category.image_brief(ctx.category_intelligence, names)
    try:
        parsed = client.call_tool(
            _extract_prompt(ctx.brand_dna, source),
            model=settings.openrouter_prompt_model,
            tool=tools.COMMON_IMAGE_CONTEXT_TOOL,
            max_tokens=_EXTRACT_MAX_TOKENS,
        )
        common = _normalize(parsed)
        if common.get("typography", {}).get("primary"):
            return common
        logger.warning("Common image-context extract missing primary typography; using fallback")
    except Exception:  # noqa: BLE001 — fallback keeps the job running
        logger.exception("Common image-context extract failed; using fallback")
    return _fallback(ctx.brand_dna, source)


def format_block(common: dict[str, Any]) -> str:
    """Stable text block embedded in every image prompt."""
    return (
        f"{COMMON_IMAGE_CONTEXT_MARKER}\n"
        f"{json.dumps(common, ensure_ascii=False, indent=2)}\n"
        "Apply this common context on every image in the set. Do not re-pick fonts, palette, "
        "or category visual norms per slot. Typography primary (and secondary if listed) must "
        "stay identical across all slots."
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
        "From Brand DNA: typography (pick ONE primary font; at most ONE secondary with fixed "
        "usage — ignore unused faces), palette accents, mood/photography style, visual "
        "guardrails / do-nots that affect pixels. Do not include voice, copy essays, or "
        "audience prose.\n\n"
        "From Category Intelligence: cross-slot visual norms for this category, on-image text "
        "density rules (phone-readable, minimal SEO-useful keywords, no fluff), shared product "
        "presentation cues. Do not copy per-slot shot briefs or long topic essays.\n\n"
        "Never invent fonts or colors not supported by the sources. When finished, call the "
        "submit_common_image_context tool.\n\n"
        "=== BRAND DNA (source) ===\n"
        f"{brand_dna.strip()}\n\n"
        "=== CATEGORY INTELLIGENCE (image-relevant distill) ===\n"
        f"{json.dumps(category_source, ensure_ascii=False, indent=2)}"
    )


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    typography_raw = raw.get("typography") if isinstance(raw.get("typography"), dict) else {}
    palette_raw = raw.get("palette") if isinstance(raw.get("palette"), dict) else {}
    category_raw = raw.get("category") if isinstance(raw.get("category"), dict) else {}

    typography = {
        "primary": str(typography_raw.get("primary") or "").strip(),
        "secondary": str(typography_raw.get("secondary") or "").strip() or None,
        "usage": str(typography_raw.get("usage") or "").strip()
        or "titles/headlines=primary; labels/body=secondary when present",
    }
    if not typography["secondary"]:
        typography.pop("secondary", None)

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

    out: dict[str, Any] = {
        "typography": typography,
        "mood": str(raw.get("mood") or "").strip() or "clean, catalog, consistent",
        "visual_guardrails": guardrail_list,
        "category": category_out,
    }
    if palette:
        out["palette"] = palette
    return out


def _fallback(brand_dna: str, category_source: dict[str, Any]) -> dict[str, Any]:
    primary = _field(brand_dna, "primary_font") or "Montserrat Bold"
    secondary = _field(brand_dna, "secondary_font")
    mood = _field(brand_dna, "visual_mood") or _field(brand_dna, "photography_style") or "clean"
    primary_colors = _field(brand_dna, "brand_colors_primary")
    secondary_colors = _field(brand_dna, "brand_colors_secondary")

    category_name = category_source.get("category") or "this category"
    keywords = category_source.get("high_value_keywords") or []
    keyword_hint = ", ".join(str(k) for k in keywords[:8]) if keywords else ""

    plan = category_source.get("image_plan") or {}
    norms: list[str] = [
        f"Follow {category_name} marketplace visual norms from Category Intelligence.",
        "Keep typography and palette identical across every slot.",
    ]
    for track in plan.values() if isinstance(plan, dict) else []:
        if isinstance(track, dict) and track.get("build_rationale"):
            norms.append(str(track["build_rationale"]).strip()[:400])
            break

    cues: list[str] = []
    if keyword_hint:
        cues.append(f"Prefer SEO-useful on-image phrases when text is needed: {keyword_hint}")

    return _normalize(
        {
            "typography": {
                "primary": primary.split(" - ")[0].strip(),
                "secondary": (secondary.split(" - ")[0].strip() if secondary else None),
                "usage": "titles/headlines=primary; labels/body=secondary when present",
            },
            "palette": {
                "primary": primary_colors,
                "secondary": secondary_colors,
                "notes": _field(brand_dna, "accent_color_rules"),
            },
            "mood": mood,
            "visual_guardrails": [
                g
                for g in [
                    _field(brand_dna, "banned_font_styles"),
                    _field(brand_dna, "banned_colors"),
                ]
                if g
            ],
            "category": {
                "visual_norms": norms,
                "on_image_text": (
                    "phone-readable; minimal SEO-useful keywords; no fluff; no internal jargon"
                ),
                "shared_product_cues": cues,
            },
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
