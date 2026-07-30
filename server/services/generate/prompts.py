import json
from typing import Any


def _replace_em_dashes(text: str) -> str:
    return text.replace("\u2014", "-").replace("\u2013", "-")


def build_text_prompt(
    *,
    brand_dna: str,
    channel_rules: dict[str, Any],
    sku_context: dict[str, Any],
    text_contract: dict[str, Any],
) -> str:
    channel_text = json.dumps(
        {
            "text_rules": channel_rules.get("text_rules", {}),
            "cost_strategy": channel_rules.get("cost_strategy", {}),
        },
        indent=2,
    )
    parts = text_contract.get("user_template", [])
    rendered: list[str] = []
    for part in parts:
        rendered.append(
            str(part)
            .replace("{{brand_dna}}", brand_dna)
            .replace("{{channel_rules_text}}", channel_text)
            .replace("{{sku_context_json}}", json.dumps(sku_context, indent=2))
        )
    system = str(text_contract.get("system", "")).strip()
    return f"{system}\n\n" + "\n\n".join(rendered)


def build_image_brief_prompt(
    *,
    brand_dna: str,
    channel_rules: dict[str, Any],
    sku_context: dict[str, Any],
    generated_text: dict[str, Any] | None,
    image_type: str,
    variant: int,
    image_contract: dict[str, Any],
    brief_contract: dict[str, Any],
    overlay_visual: dict[str, Any] | None = None,
    creative_concepts: dict[str, Any] | None = None,
    creative_angle_name: str = "",
    concept_angle: str = "",
) -> str:
    type_brief = image_contract.get("per_type_brief", {}).get(image_type, "")
    variant_brief = (
        image_contract.get("variant_briefs", {}).get(image_type, {}).get(str(variant), "")
    )
    channel_image_rules = json.dumps(channel_rules.get("image_rules", {}), indent=2)
    overlay_json = json.dumps(overlay_visual or {}, indent=2)
    concepts = creative_concepts or {}
    design_system_json = json.dumps(concepts.get("design_system") or {}, indent=2)
    creative_concepts_json = json.dumps(concepts, indent=2)
    parts = brief_contract.get("user_template", [])
    rendered: list[str] = []
    for part in parts:
        rendered.append(
            str(part)
            .replace("{{brand_dna}}", brand_dna)
            .replace("{{channel_image_rules_json}}", channel_image_rules)
            .replace("{{creative_concepts_json}}", creative_concepts_json)
            .replace("{{design_system_json}}", design_system_json)
            .replace("{{overlay_visual_json}}", overlay_json)
            .replace("{{sku_context_json}}", json.dumps(sku_context, indent=2))
            .replace("{{generated_text_json}}", json.dumps(generated_text or {}, indent=2))
            .replace("{{image_type}}", image_type)
            .replace("{{variant}}", str(variant))
            .replace("{{creative_angle_name}}", creative_angle_name)
            .replace("{{concept_angle}}", concept_angle)
            .replace("{{type_brief}}", str(type_brief))
            .replace("{{variant_brief}}", str(variant_brief))
        )
    system = str(brief_contract.get("system", "")).strip()
    return f"{system}\n\n" + "\n\n".join(rendered)


def build_image_model_prompt(
    brief: dict[str, Any],
    *,
    overlay_visual: dict[str, Any] | None = None,
) -> str:
    """Final prompt for the GPT image model. Prefer canonical render_prompt + hard guards."""
    render = brief.get("render_prompt")
    if not isinstance(render, str) or not render.strip():
        raise ValueError("Image brief missing render_prompt")

    image_type = str(brief.get("image_type") or "")
    overlays = brief.get("overlays") if isinstance(brief.get("overlays"), dict) else {}
    overlays_enabled = bool(overlays.get("enabled"))
    allow_people = image_type in {"lifestyle", "a_plus"}

    guards: list[str] = [
        "Follow render_prompt exactly.",
        "The attached image is the GROUND-TRUTH product photo.",
        "Match its curtain pattern, colors, and trim exactly.",
        "Do not invent a new print.",
        "Do not draw logos or brand wordmarks. Leave top-left clear.",
        "ASCII hyphen (-) only. No em dashes.",
        "Photoreal fabric, soft catalog daylight, sharp focus on drape folds.",
    ]
    if image_type == "lifestyle":
        guards.append(
            "MUST include one clearly visible adult lifestyle model in the room. "
            "If the model is missing, the image fails."
        )
    elif not allow_people:
        guards.append("Zero humans. Zero hands.")

    if overlays_enabled:
        guards.extend(
            [
                "OVERLAYS: use separate solid opaque white/cream cards only.",
                "Never one translucent glass slab over the product.",
                "Charcoal text, Montserrat-like headings, Open-Sans-like body.",
                "Copy callout titles exactly from overlays.callouts - no invented features.",
            ]
        )

    forbidden = brief.get("forbidden")
    if not isinstance(forbidden, list) or not forbidden:
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

    payload: dict[str, Any] = {
        "task": (
            "Generate one high-converting Amazon marketplace image "
            "from the attached raw product photo"
        ),
        "image_type": brief.get("image_type"),
        "variant": brief.get("variant"),
        "creative_angle_name": brief.get("creative_angle_name"),
        "product_visual_lock": brief.get("product_visual_lock"),
        "composition": brief.get("composition"),
        "scene": brief.get("scene"),
        "overlays": brief.get("overlays"),
        "typography": brief.get("typography"),
        "logo": {
            "draw_any_logo_or_brand_wordmark": False,
            "leave_clear_corner": "top-left",
        },
        "forbidden": forbidden,
        "render_prompt": _replace_em_dashes(render.strip()),
        "hard_guards": guards,
    }
    if overlays_enabled and overlay_visual:
        payload["overlay_visual_intelligence"] = overlay_visual
    return _replace_em_dashes(json.dumps(payload, indent=2))
