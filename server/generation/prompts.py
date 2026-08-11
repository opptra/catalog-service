"""Prompt construction. Reasons over three inputs with distinct roles:

- PRODUCT DATA — the ONLY source of product facts (authoritative).
- CATEGORY INTELLIGENCE — how to optimize the listing (strategy, positioning, messaging, image
  concepts); never a source of product facts.
- BRAND DNA — voice, personality, guardrails, restricted claims.

No hardcoded content or image templates: strategy and image direction are derived from the data.
"""

import json
from dataclasses import dataclass

from entities.catalog.attribute_enums import AttributeDataType, AttributeName
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
    "quality over completeness.\n"
    "- For ANY image: do NOT draw, render, "
    "watermark, or place any brand logo or brand name on the image. Do NOT leave empty reserved "
    "space, corners, banners, margins, or padding for a logo — the logo is added later by a "
    "deterministic code step, so compose the full frame with product/content only."
)


@dataclass(frozen=True, slots=True)
class PromptParts:
    """Stable ``prefix`` (prompt-cacheable) + variable ``suffix`` for the API wire format."""

    prefix: str
    suffix: str

    def as_sent(self) -> str:
        """Full prompt text as the model receives it (prefix then suffix)."""
        if not self.prefix:
            return self.suffix
        if not self.suffix:
            return self.prefix
        return f"{self.prefix}\n\n{self.suffix}"


def text_strategy_parts(ctx: GenerationContext, names: list[AttributeName]) -> PromptParts:
    """Strategy prompt split for caching: rules + product first; attribute/category last."""
    brief = category.text_brief(ctx.category_intelligence, names)
    attribute_list = ", ".join(name.value for name in names)
    attr_phrase = (
        f"this attribute: {attribute_list}"
        if len(names) == 1
        else f"these attributes: {attribute_list}"
    )
    prefix = f"{_RULES}\n\n{_product_block(ctx.product)}"
    suffix = (
        "You are an expert marketplace listing strategist. Produce a concise, high-signal "
        f"content strategy for generating {attr_phrase}. Base it on the "
        "Category Intelligence — positioning, differentiators, messaging, high-value keywords "
        "and customer signals (lead with what buyers praise, reassure on what they complain "
        "about). Reference the product only to tailor the angle. Output tight strategy notes in "
        "bullets, NOT final copy.\n\n"
        f"{_category_block(brief)}"
    )
    return PromptParts(prefix=prefix, suffix=suffix)


def text_strategy_prompt(ctx: GenerationContext, names: list[AttributeName]) -> str:
    """Ask for a concise, Category-Intelligence-led content strategy (not the final copy)."""
    return text_strategy_parts(ctx, names).as_sent()


def _text_tool_instruction(names: list[AttributeName]) -> str:
    """Tool-call instruction listing only the requested attributes and their types."""
    keys = ", ".join(name.value for name in names)
    field_word = "field" if len(names) == 1 else "fields"
    type_lines: list[str] = []
    for name in names:
        if name == AttributeName.BULLET_POINTS:
            type_lines.append(f'"{name.value}" must be an array of strings.')
        else:
            type_lines.append(f'"{name.value}" must be a string.')
    type_note = " ".join(type_lines)
    return (
        f"When finished, call the submit_text_attributes tool with exactly "
        f"{'this' if len(names) == 1 else 'these'} {field_word}: {keys}. "
        f"{type_note} Do not write the attribute"
        f"{'' if len(names) == 1 else 's'} as free-form JSON in the message body."
    )


def text_generation_parts(
    ctx: GenerationContext, names: list[AttributeName], strategy: str
) -> PromptParts:
    """Generation prompt split for caching: rules + product + brand; strategy/tool last."""
    target = f"the final {names[0].value}" if len(names) == 1 else "the final text attributes"
    prefix = f"{_RULES}\n\n{_product_block(ctx.product)}\n\n{_brand_block(ctx.brand_dna)}"
    suffix = (
        "You are an expert marketplace copywriter. Using the STRATEGY and the authoritative "
        f"PRODUCT DATA below, write {target}. Apply the Brand DNA voice and "
        "guardrails. Every factual claim must be supported by PRODUCT DATA; when a recommended "
        "detail is missing, adapt gracefully with neutral, high-quality copy rather than "
        "guessing.\n\n"
        f"STRATEGY:\n{strategy}\n\n"
        f"{_text_tool_instruction(names)}"
    )
    return PromptParts(prefix=prefix, suffix=suffix)


def text_generation_prompt(
    ctx: GenerationContext, names: list[AttributeName], strategy: str
) -> str:
    """Final text prompt: apply the strategy + brand voice to the authoritative product facts."""
    return text_generation_parts(ctx, names, strategy).as_sent()


def slot_brief_prompt(ctx: GenerationContext, requested: list[tuple[AttributeName, int]]) -> str:
    """Step 1: minimal gallery sequence (role / visual / objective) from Category Intelligence."""
    brief = category.image_brief(ctx.category_intelligence, [name for name, _ in requested])
    return (
        "Map Category Intelligence onto the exact image slots below. Output a gallery sequence "
        "only — not render prompts.\n\n"
        f"{_reference_photos_note(ctx.product_image_urls)}\n\n"
        "Slots required:\n"
        f"{_requested_block(requested)}\n\n"
        "For IMAGE slots, follow the category gallery arc. For A_PLUS slots, follow A+ module "
        "guidance. Every slot must be distinct.\n\n"
        "Each slot needs:\n"
        "- role: short label (e.g. HERO_LIFESTYLE, FEATURE_CALLOUT, FABRIC_TEXTURE)\n"
        "- visual: one sentence describing what the frame shows\n"
        "- objective: one short phrase for why this slot exists\n\n"
        f"{_category_block(brief)}\n\n"
        "Call submit_slot_briefs with one entry per slot (type + slot + role + visual + "
        "objective). Slot restarts at 1 within IMAGE and within A_PLUS."
    )


def gallery_plan_prompt(
    ctx: GenerationContext,
    requested: list[tuple[AttributeName, int]],
    slot_briefs: list[dict[str, object]],
) -> str:
    """Step 2: turn step-1 gallery sequence into complete standalone image-generation prompts."""
    brief = category.image_brief(ctx.category_intelligence, [name for name, _ in requested])
    briefs_json = json.dumps(slot_briefs, ensure_ascii=False, indent=2)
    return (
        "You are an expert e-commerce visual merchandiser and product-photography art director. "
        "Turn the GALLERY SEQUENCE into one complete image-generation prompt per slot, linked by "
        "a shared visual system. Honour every role/visual/objective — do not reassign slots.\n\n"
        f"{_reference_photos_note(ctx.product_image_urls)}\n\n"
        "Images to produce:\n"
        f"{_requested_block(requested)}\n\n"
        "=== GALLERY SEQUENCE ===\n"
        f"{briefs_json}\n\n"
        "For EVERY slot, expand into a complete prompt covering:\n"
        "- composition, camera, background, props, lighting, styling, visual hierarchy;\n"
        "- honesty to the attached real product (colour, form, material, finish, pattern);\n"
        "- physical coherence — product used/placed realistically;\n"
        "- on-image text/badges only when the role calls for it and marketplace rules allow;\n"
        "- never draw a brand logo/wordmark or leave reserved space for one (logo is composited "
        "later in code — state this in every prompt);\n"
        "- never mention aspect ratio, canvas shape, orientation, or pixel dimensions "
        "(the renderer fixes that).\n\n"
        "Keep the set visually linked. Product facts come ONLY from PRODUCT DATA; if a detail is "
        "missing, stay neutral. Reference photos are also given to the image model at render "
        "time.\n\n"
        f"{_RULES}\n\n"
        f"{_category_block(brief)}\n\n"
        f"{_brand_block(ctx.brand_dna)}\n\n"
        f"{_product_block(ctx.product)}\n\n"
        "When finished, call submit_gallery_plan with shared_style and one slots entry per "
        "requested (type, slot). Each prompt must be complete and standalone. Slot restarts at 1 "
        "within each type."
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


def revise_generation_prompt(
    *,
    data_type: AttributeDataType,
    attribute_name: AttributeName,
    previous_prompt: str,
    current_value: str,
    improvement: str,
) -> str:
    """Ask the prompt model to produce a revised generation prompt from user feedback."""
    kind = "image" if data_type == AttributeDataType.IMAGE else "text"
    current_block = (
        "CURRENT OUTPUT: an image is attached as vision input (the latest generated result)."
        if data_type == AttributeDataType.IMAGE
        else f"CURRENT OUTPUT (text):\n{current_value}"
    )
    return (
        f"You revise marketplace {kind}-generation prompts. Attribute: {attribute_name.value}.\n"
        "Combine the PREVIOUS PROMPT with the USER IMPROVEMENT into one complete, standalone "
        f"{kind}-generation prompt that will be sent to the model as-is.\n"
        "Keep everything that still applies from the previous prompt. Apply the user's requested "
        "changes precisely. Do not invent product facts. Do not mention aspect ratio or brand-logo "
        "placement (those are handled elsewhere).\n"
        "When finished, call the submit_revised_prompt tool with the final prompt string — do not "
        "write the prompt as free-form JSON in the message body.\n\n"
        f"PREVIOUS PROMPT:\n{previous_prompt}\n\n"
        f"{current_block}\n\n"
        f"USER IMPROVEMENT:\n{improvement.strip()}"
    )
