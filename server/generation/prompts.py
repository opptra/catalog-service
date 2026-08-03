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
    keys = ", ".join(name.value for name in names)
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
        f"When finished, call the submit_text_attributes tool with exactly these fields: {keys}. "
        f'"{AttributeName.BULLET_POINTS.value}" must be an array of strings; all other fields '
        "must be strings. Do not write the attributes as free-form JSON in the message body."
    )


def gallery_plan_prompt(ctx: GenerationContext, requested: list[tuple[AttributeName, int]]) -> str:
    """Category-agnostic brief: plan ONE coherent, non-duplicated image gallery via a tool call.

    The model decides each image's role, composition and on-image text from the Category
    Intelligence + Brand DNA + the attached real product image — no per-type templates and no
    category-specific vocabulary in this prompt. Two things are deliberately NOT the model's job:
    aspect ratio (the renderer uses a fixed ratio per image type) and brand-logo placement (the
    logo is composited deterministically downstream, not drawn by the image model).
    """
    brief = category.image_brief(ctx.category_intelligence, [name for name, _ in requested])
    slot_rule = (
        "In the tool call, slot is 1-based and restarts at 1 within EACH type — it is not a "
        "running count across the whole gallery. E.g. if INFOGRAPHIC needs 2 images, they are "
        "type=INFOGRAPHIC slot=1 and type=INFOGRAPHIC slot=2, regardless of how many other "
        "types/slots precede them."
    )
    return (
        "You are an expert e-commerce visual merchandiser and product-photography art director. "
        "Design a COHERENT image gallery for ONE product. You are given the exact set of images to "
        "produce (by type and count). Decide from the Category Intelligence gallery guidance, the "
        "Brand DNA visual identity, and the attached product image(s) — what each image should "
        "be so that together they form one connected, non-duplicated gallery.\n\n"
        f"{_reference_photos_note(ctx.product_image_urls)}\n\n"
        "Images to produce (submit EXACTLY one plan entry per slot via the tool):\n"
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
        "- do NOT place any brand logo or brand name on the image — the logo is added later by a "
        "separate deterministic step, so never draw, render or leave space for it;\n"
        "- do NOT choose or mention an aspect ratio, canvas shape, orientation or pixel/format "
        "dimensions anywhere — the renderer uses a fixed ratio per image type, so compose for the "
        "subject and leave the canvas shape entirely to the system.\n\n"
        "Keep the whole set LINKED via one shared visual system so every image clearly belongs to "
        "the same product and brand. Use product facts ONLY from PRODUCT DATA; if a helpful detail "
        "is missing, stay neutral — never fabricate. The real product reference image(s) are also "
        "supplied to the image model at render time.\n\n"
        f"{_RULES}\n\n"
        f"{_category_block(brief)}\n\n"
        f"{_brand_block(ctx.brand_dna)}\n\n"
        f"{_product_block(ctx.product)}\n\n"
        "When finished, call the submit_gallery_plan tool with shared_style and one slots entry "
        "for each requested (type, slot). Each prompt must be a complete, standalone "
        "image-generation prompt that incorporates the shared_style and every decision above. "
        "Do not write the plan as free-form JSON in the message body.\n"
        f"{slot_rule}"
    )


def _requested_block(requested: list[tuple[AttributeName, int]]) -> str:
    lines = [f"- {name.value}: {quantity} image(s)" for name, quantity in requested]
    total = sum(quantity for _, quantity in requested)
    return "\n".join(lines) + f"\nTotal: {total} images."


def _product_block(product: dict) -> str:
    # source_assets is dropped from the text block: the images it points to are attached above as
    # actual vision inputs, so repeating their raw URLs here is noise, not signal.
    facts = {key: value for key, value in product.items() if key != "source_assets"}
    return (
        "=== PRODUCT DATA (authoritative — the ONLY source of product facts) ===\n"
        f"{json.dumps(facts, ensure_ascii=False, indent=2)}"
    )


def _reference_photos_note(image_urls: list[str]) -> str:
    count = len(image_urls)
    if not count:
        return "No real product reference photos were available for this product."
    return (
        f"You are attached {count} real reference photo(s) of this exact product, taken from its "
        "actual marketplace listing (different angles/closeups of the same physical item, in "
        "listing order). Cross-reference all of them together as the single source of truth for "
        "its true colour, pattern, texture, materials and construction — do not rely on only one "
        "angle or assume a detail that isn't visible in any of them."
    )


def _category_block(brief: dict) -> str:
    return (
        "=== CATEGORY INTELLIGENCE (how to optimize — NOT a source of product facts) ===\n"
        f"{json.dumps(brief, ensure_ascii=False, indent=2)}"
    )


def _brand_block(brand_dna: str) -> str:
    return f"=== BRAND DNA (voice, personality, guardrails, restricted claims) ===\n{brand_dna}"
