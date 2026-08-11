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
from generation import category, tools
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
    "- For ANY image (hero, infographic, lifestyle, A+, or any other type): do NOT draw, render, "
    "watermark, or place any brand logo or brand name on the image. Do NOT leave empty reserved "
    "space, corners, banners, margins, or padding for a logo — the logo is added later by a "
    "deterministic code step, so compose the full frame with product/content only."
)


# Per-attribute role guidance appended to text generation prompts. Numeric limits
# are NOT written here — they come from tools.TEXT_LIMITS via tools.limit_sentence
# so each number exists in exactly one place.
_ATTRIBUTE_GUIDANCE: dict[AttributeName, str] = {
    AttributeName.TITLE: (
        "Order: brand first, then the primary search keyword, then one real "
        "differentiator, then a variant (colour/size/pack) if it fits. Title Case, "
        "no promotional or subjective words, no ALL-CAPS words."
    ),
    AttributeName.ITEM_HIGHLIGHTS: (
        "Amazon's Item Highlights field is shown directly beneath the title in search "
        "results and on the product page. Write ONE natural phrase (not a keyword list, "
        "not bullet style) carrying the strongest secondary facts that are NOT already "
        "in the title: materials, use case, age range, pack size, certifications. "
        "Never repeat the title."
    ),
    AttributeName.BULLET_POINTS: (
        "Benefit-led Feature-then-Benefit sentences; lead each bullet with what buyers "
        "care about most. No keyword stuffing."
    ),
    AttributeName.BACKEND_KEYWORDS: (
        "Amazon's hidden backend search terms field — never shown to shoppers, indexed "
        "for search only. Space-separated terms, no commas or semicolons, no brand or "
        "competitor names, no words already in the title. Prefer long-tail and "
        "regional/vernacular synonyms shoppers search for but that do not fit natural "
        "listing copy."
    ),
}


def attribute_rules(name: AttributeName) -> str:
    """Guidance + hard-limit sentence for one text attribute ('' when none apply)."""
    lines: list[str] = []
    guidance = _ATTRIBUTE_GUIDANCE.get(name)
    if guidance:
        lines.append(guidance)
    limit = tools.limit_sentence(name)
    if limit:
        lines.append(limit)
    return " ".join(lines)


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
        if name in tools.LIST_TEXT_ATTRIBUTES:
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


def _attribute_rules_block(names: list[AttributeName]) -> str:
    """ATTRIBUTE RULES section listing guidance + hard limits per requested attribute."""
    lines = [
        f"- {name.value}: {rules}" for name in names if (rules := attribute_rules(name))
    ]
    if not lines:
        return ""
    return "ATTRIBUTE RULES (hard requirements, checked in code after generation):\n" + "\n".join(
        lines
    )


def text_generation_parts(
    ctx: GenerationContext, names: list[AttributeName], strategy: str
) -> PromptParts:
    """Generation prompt split for caching: rules + product + brand; strategy/tool last."""
    target = f"the final {names[0].value}" if len(names) == 1 else "the final text attributes"
    prefix = f"{_RULES}\n\n{_product_block(ctx.product)}\n\n{_brand_block(ctx.brand_dna)}"
    rules_block = _attribute_rules_block(names)
    suffix = (
        "You are an expert marketplace copywriter. Using the STRATEGY and the authoritative "
        f"PRODUCT DATA below, write {target}. Apply the Brand DNA voice and "
        "guardrails. Every factual claim must be supported by PRODUCT DATA; when a recommended "
        "detail is missing, adapt gracefully with neutral, high-quality copy rather than "
        "guessing.\n\n"
        + (f"{rules_block}\n\n" if rules_block else "")
        + f"STRATEGY:\n{strategy}\n\n"
        f"{_text_tool_instruction(names)}"
    )
    return PromptParts(prefix=prefix, suffix=suffix)


def text_generation_prompt(
    ctx: GenerationContext, names: list[AttributeName], strategy: str
) -> str:
    """Final text prompt: apply the strategy + brand voice to the authoritative product facts."""
    return text_generation_parts(ctx, names, strategy).as_sent()


def key_features_parts(
    ctx: GenerationContext, *, description: str, bullet_points: list[str]
) -> PromptParts:
    """KEY_FEATURES prompt: condense the already-written Description + Bullet Points.

    Amazon's Key Product Features flat-file field is separate from the five Bullet
    Points columns: five short standalone lines. This is a derivation step — it never
    re-researches from Category Intelligence, only compresses copy that has already
    been generated and persisted for this SKU.
    """
    name = AttributeName.KEY_FEATURES
    bullets_block = "\n".join(f"- {bullet}" for bullet in bullet_points)
    prefix = f"{_RULES}\n\n{_product_block(ctx.product)}\n\n{_brand_block(ctx.brand_dna)}"
    suffix = (
        "You are an expert marketplace copywriter. Write Amazon's KEY PRODUCT FEATURES "
        "field: five short standalone feature phrases (not full sentences), one per line "
        "slot. Condense and rephrase the ALREADY-WRITTEN Bullet Points and Description "
        "below — do not introduce any fact that is not in them or in PRODUCT DATA, and do "
        "not simply copy a bullet verbatim.\n\n"
        f"{_attribute_rules_block([name])}\n\n"
        f"ALREADY-WRITTEN BULLET POINTS:\n{bullets_block}\n\n"
        f"ALREADY-WRITTEN DESCRIPTION:\n{description}\n\n"
        f"{_text_tool_instruction([name])}"
    )
    return PromptParts(prefix=prefix, suffix=suffix)


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
        "- brand logo: never draw/render a logo or brand wordmark, and never leave reserved "
        "space for one — every slot prompt must state this explicitly; the logo is composited "
        "later in code;\n"
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
