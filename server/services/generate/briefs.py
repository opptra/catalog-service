"""Normalize and strengthen image briefs before the image model runs.

The vision/text model often returns partial or nested JSON. We never pass a weak
or contradictory render_prompt to the image model.
"""

from __future__ import annotations

from typing import Any

from core.exceptions import GenerateError

_EM_DASHES = str.maketrans({"\u2014": "-", "\u2013": "-"})


def _strip_em_dashes(text: str) -> str:
    return text.translate(_EM_DASHES)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_nonempty_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_nested_render(brief: dict[str, Any]) -> str:
    """Pull render_prompt from common malformed nesting shapes."""
    direct = brief.get("render_prompt")
    if isinstance(direct, str) and direct.strip():
        # Reject known weak synthesizer leftovers if a richer nested prompt exists.
        weak = direct.strip().lower().startswith("create a marketplace")
        concept = _as_dict(brief.get("concept"))
        nested = concept.get("render_prompt")
        if weak and isinstance(nested, str) and nested.strip():
            return nested.strip()
        return direct.strip()

    for key in ("concept", "brief", "image_brief", "creative"):
        nested = _as_dict(brief.get(key)).get("render_prompt")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    return ""


def _normalize_overlays(
    brief: dict[str, Any],
    *,
    image_type: str,
    highlights: list[str],
) -> dict[str, Any]:
    overlays = _as_dict(brief.get("overlays"))
    if not overlays:
        overlays = _as_dict(brief.get("overlay"))

    callouts = _as_list(overlays.get("callouts"))
    if not callouts:
        callouts = _as_list(brief.get("callouts"))

    needs_overlays = image_type in {"infographic", "a_plus"}
    normalized_callouts: list[dict[str, str]] = []
    for item in callouts:
        if not isinstance(item, dict):
            continue
        title = _first_nonempty_str(item.get("title"), item.get("name"), item.get("label"))
        detail = _first_nonempty_str(item.get("detail"), item.get("description"), item.get("body"))
        if title:
            normalized_callouts.append(
                {
                    "title": _strip_em_dashes(title)[:80],
                    "detail": _strip_em_dashes(detail)[:120] if detail else "",
                }
            )

    if needs_overlays and not normalized_callouts and highlights:
        for title in highlights[:6]:
            if isinstance(title, str) and title.strip():
                normalized_callouts.append(
                    {"title": _strip_em_dashes(title.strip())[:80], "detail": ""}
                )

    if needs_overlays:
        return {
            "enabled": True,
            "style": "side_panel_icons",
            "card_background": "solid opaque white",
            "heading_font": "Montserrat Bold like",
            "body_font": "Open Sans Regular like",
            "text_color": "#2F2F2F",
            "border_accent": "#DCC7A1",
            "callouts": normalized_callouts[:6],
        }

    return {
        "enabled": False,
        "style": "none",
        "callouts": [],
    }


def _observed_lock(brief: dict[str, Any], sku_context: dict[str, Any]) -> str:
    lock = _as_dict(brief.get("product_visual_lock"))
    observed = _first_nonempty_str(
        lock.get("observed_from_reference_photo"),
        brief.get("product_lock"),
        sku_context.get("product_name"),
    )
    return _strip_em_dashes(observed)


def build_canonical_render_prompt(
    *,
    image_type: str,
    variant: int,
    creative_angle_name: str,
    concept_angle: str,
    sku_context: dict[str, Any],
    generated_text: dict[str, Any] | None,
    brief: dict[str, Any],
    model_render: str,
) -> str:
    """Deterministic high-signal prompt. Model prose is enrichment, never the sole source."""
    product_name = str(sku_context.get("product_name") or "curtain product")
    observed = _observed_lock(brief, sku_context)
    highlights = []
    if isinstance(generated_text, dict):
        raw_highlights = generated_text.get("item_highlights") or []
        if isinstance(raw_highlights, list):
            highlights = [str(h).strip() for h in raw_highlights if str(h).strip()]

    overlays = _as_dict(brief.get("overlays"))
    callouts = _as_list(overlays.get("callouts"))
    callout_lines: list[str] = []
    for item in callouts:
        if isinstance(item, dict) and item.get("title"):
            title = str(item["title"]).strip()
            detail = str(item.get("detail") or "").strip()
            callout_lines.append(f'"{title}"' + (f" ({detail})" if detail else ""))

    parts: list[str] = [
        f"Amazon India marketplace {image_type} image, variant {variant}.",
        f"Creative angle: {creative_angle_name}." if creative_angle_name else "",
        concept_angle,
        f"PRODUCT: {product_name}.",
        f"PRODUCT LOCK from raw reference photo: {observed}."
        if observed
        else (
            "PRODUCT LOCK: match the attached raw product photo exactly for color, "
            "pattern motif, fabric texture, trim, and panel count."
        ),
        (
            "CRITICAL PRODUCT FIDELITY: do not redesign the curtain print. "
            "Copy the exact motif, colorway, and edge details from the reference photo. "
            "If unsure, stay closer to the photo than inventing a prettier pattern."
        ),
        "Photoreal catalog quality. Soft even daylight on fabric folds.",
        "No HDR bloom. No cartoon look.",
        "Do not draw any logo, wordmark, watermark, or brand badge.",
        "Leave top-left corner empty for post stamp.",
        "No em dashes. No invented dimensions or care claims.",
        "No invented hardware unless clearly visible in the photo.",
    ]

    if image_type == "hero":
        parts.extend(
            [
                "HERO RULES: clean interior, curtain is the only hero.",
                "Full-length drape fills frame.",
                "NO people, NO hands, NO text overlays, NO callout cards, NO badges.",
            ]
        )
    elif image_type == "infographic":
        parts.extend(
            [
                "INFOGRAPHIC RULES: curtain dominant on left/center (~60%+ of frame).",
                "Right third: 4-6 SEPARATE solid opaque white/cream rounded cards with soft shadow "
                "and thin warm-beige border. NEVER one big translucent glass panel.",
                "Card text: charcoal #2F2F2F, Montserrat-Bold-like titles,",
                "Open-Sans-like short details.",
                "NO people, NO hands.",
                "Callout titles must be exactly these highlights (do not invent features): "
                + "; ".join(callout_lines or [f'"{h}"' for h in highlights]),
            ]
        )
    elif image_type == "lifestyle":
        parts.extend(
            [
                "LIFESTYLE HARD REQUIREMENT: show ONE clearly visible adult (age ~24-40) "
                "reading, with coffee, or relaxing in a modern Indian home. "
                "Model must be recognizable and not tiny/cropped out.",
                "Curtain remains the visual hero; pattern fully readable.",
                "Model must not cover the print.",
                "Editorial depth: architectural room, deep fabric folds, natural window light.",
                "NO text overlays, NO callout cards, NO people crowds, NO children.",
            ]
        )
    elif image_type == "a_plus":
        parts.extend(
            [
                "A+ MODULE: wide premium Amazon A+ panel composition.",
                "Full-bleed room photography with curtain dominant.",
                "Optional soft-background adult only.",
                "3-5 separate solid white/cream benefit chips (not one translucent slab) with "
                "exact highlight titles only.",
                "Callouts: " + "; ".join(callout_lines or [f'"{h}"' for h in highlights]),
            ]
        )

    # Keep useful model prose if it does not contradict people rules.
    cleaned_model = _strip_em_dashes(model_render.strip())
    if cleaned_model and not cleaned_model.lower().startswith("create a marketplace"):
        lower = cleaned_model.lower()
        if image_type == "lifestyle" and "no human" in lower:
            cleaned_model = ""
        if image_type in {"hero", "infographic"} and "adult" in lower and "required" in lower:
            # avoid accidental people injection on no-people types
            pass
        if cleaned_model:
            parts.append(f"Director notes: {cleaned_model}")

    return _strip_em_dashes(" ".join(part for part in parts if part))


def normalize_image_brief(
    brief: dict[str, Any],
    *,
    image_type: str,
    variant: int,
    creative_angle_name: str,
    concept_angle: str,
    sku_context: dict[str, Any],
    generated_text: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(brief, dict):
        raise GenerateError("Image brief JSON must be an object")

    highlights: list[str] = []
    if isinstance(generated_text, dict):
        raw = generated_text.get("item_highlights") or []
        if isinstance(raw, list):
            highlights = [str(h) for h in raw if str(h).strip()]

    model_render = _extract_nested_render(brief)
    overlays = _normalize_overlays(brief, image_type=image_type, highlights=highlights)

    lock = _as_dict(brief.get("product_visual_lock"))
    if not lock.get("observed_from_reference_photo"):
        lock = {
            "observed_from_reference_photo": _observed_lock(brief, sku_context),
            "must_preserve": [
                "color",
                "pattern",
                "fabric_texture",
                "trim_if_visible",
                "panel_count",
            ],
        }

    scene = _as_dict(brief.get("scene"))
    composition = _as_dict(brief.get("composition"))

    allow_people = image_type in {"lifestyle", "a_plus"}
    forbidden = [
        "invented logos",
        "em dashes",
        "invented dimensions",
        "cartoon style",
        "translucent glass overlay panels",
        "blurry overlay text",
        "script fonts",
        "redesigned curtain pattern",
    ]
    if not allow_people:
        forbidden = ["humans", "hands", *forbidden]
    if image_type == "lifestyle":
        forbidden = [f for f in forbidden if f not in {"humans", "hands"}]

    normalized: dict[str, Any] = {
        "image_type": image_type,
        "variant": variant,
        "creative_angle_name": creative_angle_name,
        "concept_angle": concept_angle,
        "product_visual_lock": lock,
        "composition": composition
        or {
            "camera": "eye-level",
            "framing": "product-dominant",
            "product_hero_priority": "dominant",
        },
        "scene": scene
        or {
            "room_type": "modern Indian living room",
            "mood": "clean premium catalog",
            "lighting": "soft even catalog daylight",
        },
        "overlays": overlays,
        "typography": {
            "heading_style": "Montserrat Bold, high legibility",
            "body_style": "Open Sans Regular, readable",
            "contrast": "charcoal on solid light card",
        },
        "logo": {
            "draw_any_logo_or_brand_wordmark": False,
            "leave_clear_corner": "top-left",
        },
        "forbidden": forbidden,
    }
    normalized["render_prompt"] = build_canonical_render_prompt(
        image_type=image_type,
        variant=variant,
        creative_angle_name=creative_angle_name,
        concept_angle=concept_angle,
        sku_context=sku_context,
        generated_text=generated_text,
        brief=normalized,
        model_render=model_render,
    )
    return normalized
