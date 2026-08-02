"""Prompt construction. Reasons over three inputs with distinct roles:

- PRODUCT DATA — the ONLY source of product facts (authoritative).
- CATEGORY INTELLIGENCE — how to optimize the listing (strategy, positioning, messaging, image
  concepts); never a source of product facts.
- BRAND DNA — voice, personality, guardrails, restricted claims.

No hardcoded content or image templates: strategy and image direction are derived from the data.
"""

import json

from entities.catalog.attribute_enums import AttributeName
from generation import category
from generation.context import GenerationContext

# Shared rules applied to every generation call.
_RULES = (
    "RULES:\n"
    "- Product facts (materials, dimensions, colour, pack size, care, weight, etc.) come ONLY "
    "from PRODUCT DATA. Never invent, infer, or import facts from Category Intelligence.\n"
    "- If Category Intelligence recommends a detail that PRODUCT DATA does not contain, omit it "
    "or stay neutral — never fabricate values or make unsupported claims.\n"
    "- Use Category Intelligence for strategy, positioning, messaging, differentiators and "
    "keywords; use Brand DNA for tone, personality and restricted claims. Do not let Brand DNA "
    "override category best practices unless a brand guardrail requires it.\n"
    "- Optimize for listing quality, customer trust, marketplace compliance and conversion — "
    "quality over completeness."
)


def text_strategy_prompt(ctx: GenerationContext, names: list[AttributeName]) -> str:
    """Ask for a concise, Category-Intelligence-led content strategy (not the final copy)."""
    brief = category.text_brief(ctx.category_intelligence, names)
    attribute_list = ", ".join(name.value for name in names)
    return (
        "You are an expert marketplace listing strategist. Produce a concise, high-signal "
        f"content strategy for generating these attributes: {attribute_list}. Base it on the "
        "Category Intelligence — positioning, differentiators, messaging, high-value keywords "
        "and customer signals (lead with what buyers praise, reassure on what they complain "
        "about). Reference the product only to tailor the angle. Output tight strategy notes in "
        "bullets, NOT final copy.\n\n"
        f"{_RULES}\n\n"
        f"{_category_block(brief)}\n\n"
        f"{_product_block(ctx.product)}"
    )


def text_generation_prompt(
    ctx: GenerationContext, names: list[AttributeName], strategy: str
) -> str:
    """Final text prompt: apply the strategy + brand voice to the authoritative product facts."""
    return (
        "You are an expert marketplace copywriter. Using the STRATEGY and the authoritative "
        "PRODUCT DATA below, write the final text attributes. Apply the Brand DNA voice and "
        "guardrails. Every factual claim must be supported by PRODUCT DATA; when a recommended "
        "detail is missing, adapt gracefully with neutral, high-quality copy rather than "
        "guessing.\n\n"
        f"STRATEGY:\n{strategy}\n\n"
        f"{_RULES}\n\n"
        f"{_product_block(ctx.product)}\n\n"
        f"{_brand_block(ctx.brand_dna)}\n\n"
        f"{_text_format_instruction(names)}"
    )


def gallery_plan_prompt(ctx: GenerationContext, requested: list[tuple[AttributeName, int]]) -> str:
    """Category-agnostic brief: plan ONE coherent, non-duplicated image gallery as strict JSON.

    The model decides each image's role, composition, aspect ratio, on-image text and logo placement
    from the Category Intelligence + Brand DNA + the attached real product image — no per-type
    templates and no category-specific vocabulary in this prompt.
    """
    brief = category.image_brief(ctx.category_intelligence)
    schema = (
        "{\n"
        '  "shared_style": "<one paragraph: the visual system linking every image — palette, mood, '
        'product rendering, lighting>",\n'
        '  "slots": [\n'
        '    {"type": "<TYPE>", "slot": <n>, "concept": "<short label>", "aspect_ratio": "<w:h>", '
        '"prompt": "<complete standalone image-generation prompt for this slot>"}\n'
        "  ]\n"
        "}"
    )
    slot_rule = (
        '"slot" is 1-based and restarts at 1 within EACH type — it is not a running count across '
        "the whole gallery. E.g. if INFOGRAPHIC needs 2 images, they are "
        '{"type": "INFOGRAPHIC", "slot": 1, ...} and {"type": "INFOGRAPHIC", "slot": 2, ...}, '
        "regardless of how many other types/slots precede them."
    )
    return (
        "You are an expert e-commerce visual merchandiser and product-photography art director. "
        "Design a COHERENT image gallery for ONE product. You are given the exact set of images to "
        "produce (by type and count). Decide from the Category Intelligence gallery guidance, the "
        "Brand DNA visual identity, and the attached product image(s) — what each image should "
        "be so that together they form one connected, non-duplicated gallery.\n\n"
        "Images to produce (output EXACTLY one plan entry per slot):\n"
        f"{_requested_block(requested)}\n\n"
        "For EVERY slot, reason it out (do NOT use fixed templates) and decide:\n"
        "- the role/objective for a high-converting, policy-compliant listing in this "
        "marketplace/category;\n"
        "- a DISTINCT concept drawn from the category's own gallery arc — no slot may duplicate "
        "another;\n"
        "- composition, camera angle, background, props, lighting, styling and visual hierarchy;\n"
        "- honesty: the depiction must NOT contradict the attached real product (its colour, form, "
        "material, finish, pattern) — never render it as something it is not;\n"
        "- physical coherence: show the product realistically and correctly used/placed;\n"
        "- on-image text/badges appropriate to this image role and the marketplace's compliance "
        "rules (a strict primary/main image carries no text or badges; secondary images may);\n"
        "- brand-logo placement: the logo belongs on EVERY image, including the primary/main "
        "image — always small, non-intrusive and never covering the product's focal details;\n"
        "- the optimal aspect_ratio for this image role and product.\n\n"
        "Keep the whole set LINKED via one shared visual system so every image clearly belongs to "
        "the same product and brand. Use product facts ONLY from PRODUCT DATA; if a helpful detail "
        "is missing, stay neutral — never fabricate. The real product reference image(s) and the "
        "brand logo are also supplied to the image model at render time.\n\n"
        f"{_RULES}\n\n"
        f"{_category_block(brief)}\n\n"
        f"{_brand_block(ctx.brand_dna)}\n\n"
        f"{_product_block(ctx.product)}\n\n"
        "Return ONLY a valid JSON object (no markdown, no commentary) with this exact shape:\n"
        f"{schema}\n"
        f"{slot_rule}\n"
        'Include one slots entry for each requested (type, slot). Each "prompt" must be a '
        "complete, standalone image-generation prompt that incorporates the shared_style and "
        "every decision above."
    )


def _requested_block(requested: list[tuple[AttributeName, int]]) -> str:
    lines = [f"- {name.value}: {quantity} image(s)" for name, quantity in requested]
    total = sum(quantity for _, quantity in requested)
    return "\n".join(lines) + f"\nTotal: {total} images."


def _text_format_instruction(names: list[AttributeName]) -> str:
    keys = [name.value for name in names]
    return (
        "Return ONLY a valid JSON object (no markdown, no commentary) with exactly these keys: "
        f"{json.dumps(keys)}. "
        f'"{AttributeName.BULLET_POINTS.value}" must be a JSON array of strings; all other '
        "values must be strings."
    )


def _product_block(product: dict) -> str:
    return (
        "=== PRODUCT DATA (authoritative — the ONLY source of product facts) ===\n"
        f"{json.dumps(product, ensure_ascii=False, indent=2)}"
    )


def _category_block(brief: dict) -> str:
    return (
        "=== CATEGORY INTELLIGENCE (how to optimize — NOT a source of product facts) ===\n"
        f"{json.dumps(brief, ensure_ascii=False, indent=2)}"
    )


def _brand_block(brand_dna: str) -> str:
    return f"=== BRAND DNA (voice, personality, guardrails, restricted claims) ===\n{brand_dna}"
