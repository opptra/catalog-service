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
from pipelines.generation import category, common_image, tools
from pipelines.generation.context import GenerationContext

# Single source: constraints for copy and branding drawn ON generated listing images.
_IMAGE_RENDER_RULES_MARKER = "=== IMAGE RENDER RULES ==="

_IMAGE_ON_CANVAS_COPY_RULES = (
    "ON-IMAGE COPY (shopper-facing only):\n"
    "- Every headline, badge, and label on the artwork must read as normal product copy a "
    "shopper sees on the live listing.\n"
    "- NEVER render internal or ops jargon on the image — including A+, A Plus, A+ Content, "
    "A+ Features, A+ Care, Enhanced Brand Content, EBC, PDP, gallery slot, IMAGE, A_PLUS, "
    'module names, attribute type codes, or phrases like "A plus module works included".\n'
    "- Planning hints (IMAGE/A_PLUS slots, CI role/kind/pattern codes) are for you only; "
    "translate them into real messaging (e.g. Features, Care instructions, King bed fit) — "
    "never print the hint labels.\n"
    "- NEVER render font family / typeface names on the artwork (e.g. Open Sans, Montserrat, "
    'Arial, "Font: …"). Use typography visually only; shoppers must not see font labels.\n'
    "- Factual size/fit labels are fine when shopper-facing (e.g. King Size, Fits King Bed) — "
    "not prefixed with A+ or module jargon."
)

_IMAGE_LOGO_RULES = (
    "Brand logo: do not draw, render, watermark, or place any brand logo or brand name on the "
    "image. Do not leave empty reserved space, corners, banners, margins, or padding for a logo "
    "— the logo is added later by a deterministic code step."
)

# Shared rules applied to every generation call (text and image planning).
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


# Per-attribute role guidance. Soft length targets live on the tool property
# descriptions (tools.TEXT_LIMITS); hard oversize is fitted in Python after the call.
_ATTRIBUTE_GUIDANCE: dict[AttributeName, str] = {
    AttributeName.TITLE: (
        "Order: brand first, then the primary search keyword, then one real "
        "differentiator, then a variant (colour/size/pack) if it fits. Title Case, "
        "no promotional or subjective words, no ALL-CAPS words. Plan the title to "
        "land a few characters under the ceiling as a finished phrase — never cut "
        "mid-word or mid-phrase. If the full stack will not fit, drop the "
        "lowest-priority trailing element (usually the variant) before you submit."
    ),
    AttributeName.ITEM_HIGHLIGHTS: (
        "Amazon's Item Highlights field is shown directly beneath the title in search "
        "results and on the product page. Write ONE natural phrase (not a keyword list, "
        "not bullet style) carrying the strongest secondary facts that are NOT already "
        "in the title: materials, use case, age range, pack size, certifications. "
        "Never repeat the title. End on a complete clause — if length is tight, drop "
        "the least important trailing fact rather than truncating mid-phrase."
    ),
    AttributeName.BULLET_POINTS: (
        "Benefit-led Feature-then-Benefit sentences; lead each bullet with what buyers "
        "care about most. No keyword stuffing."
    ),
    AttributeName.BACKEND_KEYWORDS: (
        "Amazon's hidden backend search terms field — never shown to shoppers, indexed "
        "for search only. Return an ARRAY of terms (one term or short phrase per item). "
        "No commas or semicolons inside an item, no brand or competitor names, no words "
        "already in the title. Prefer long-tail and regional/vernacular synonyms shoppers "
        "search for but that do not fit natural listing copy."
    ),
}


def attribute_rules(name: AttributeName) -> str:
    """Role guidance for one text attribute ('' when none apply)."""
    return _ATTRIBUTE_GUIDANCE.get(name, "")


def image_on_canvas_copy_rules() -> str:
    """Single source for shopper-facing on-image copy rules (plan + revise prompts)."""
    return _IMAGE_ON_CANVAS_COPY_RULES


def image_render_prompt_suffix() -> str:
    """Single source appended to every prompt sent to the image model."""
    return f"{_IMAGE_RENDER_RULES_MARKER}\n{_IMAGE_LOGO_RULES}\n\n{_IMAGE_ON_CANVAS_COPY_RULES}"


def ensure_image_render_suffix(prompt: str) -> str:
    """Idempotently attach render rules so storage and re-render stay aligned."""
    if _IMAGE_RENDER_RULES_MARKER in prompt:
        return prompt
    stripped = prompt.strip()
    if not stripped:
        return image_render_prompt_suffix()
    return f"{stripped}\n\n{image_render_prompt_suffix()}"


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
    """ATTRIBUTE RULES section listing role guidance per requested attribute."""
    lines = [f"- {name.value}: {rules}" for name in names if (rules := attribute_rules(name))]
    if not lines:
        return ""
    return "ATTRIBUTE RULES:\n" + "\n".join(lines)


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


def gallery_plan_prompt(ctx: GenerationContext, name: AttributeName, quantity: int) -> str:
    """Plan exactly ``quantity`` slots for one image attribute type via a tool call.

    IMAGE (PDP gallery) and A_PLUS are planned in separate calls so each gets a focused
    role palette from CI ``image_plan``. Aspect ratio and logo placement stay out of the
    model's job (fixed per attribute type in code; logo composited downstream).

    Full Brand DNA is NOT included — use ``ctx.common_image_context`` (palette/mood +
    category visual bits). Named Brand DNA fonts are not forced; typography stays free.
    """
    brief = category.image_brief(ctx.category_intelligence, [name])
    type_label = (
        "product gallery" if name == AttributeName.IMAGE else "enhanced brand / feature modules"
    )
    common_block = (
        common_image.format_block(ctx.common_image_context)
        if ctx.common_image_context
        else (
            "=== COMMON IMAGE CONTEXT ===\n"
            "(missing — keep the set cohesive via mood/palette; choose typography freely; "
            "never print font family names on the artwork)"
        )
    )
    return (
        "You are an expert e-commerce visual merchandiser and product-photography art director. "
        f"Design a COHERENT {type_label} image set for ONE product. Produce EXACTLY {quantity} "
        f"image(s) for internal type {name.value} — count is fixed by the job; do not add, drop, "
        "or replace it with recommended_build. Use COMMON IMAGE CONTEXT and the attached "
        "product image(s) so the set forms one connected, non-redundant series. Choose clean "
        "readable typography freely (do not lock Brand DNA font names); keep cohesion via "
        "palette, mood, and hierarchy — never print typeface names on the artwork.\n\n"
        f"{_IMAGE_ON_CANVAS_COPY_RULES}\n\n"
        "ROLE PALETTE (image_plan when present):\n"
        f"- CATEGORY INTELLIGENCE.image_plan.{name.value} is the recommended role palette for "
        "this type — guidance, not a locked recipe.\n"
        "- Prefer priority=core roles as the main ideas. Use extended only when the requested "
        "count needs more distinct roles than core provides.\n"
        "- If N ≤ number of core roles: pick N distinct core roles "
        "(do not invent near-duplicates).\n"
        "- If N > core: cover core first, then use extended (or invent complementary distinct "
        "roles) for the remainder — still no duplicates.\n"
        "- Do NOT copy CI text verbatim onto the image; translate role/kind/pattern/content into "
        "a concrete render prompt for THIS product + COMMON IMAGE CONTEXT.\n"
        "- Topic playbook is supporting context only; image_plan is the primary role guidance "
        "when present.\n\n"
        "NON-REDUNDANCY (mandatory):\n"
        "- Every slot must have a clearly different role and visual concept.\n"
        "- No two slots may look like the same shot with minor tweaks (same angle, setting, "
        "info density, or lifestyle framing).\n"
        "- Make the difference obvious in composition, camera, background, props, and on-image "
        "information load; each concept field must name a distinct role.\n"
        "- Facts must not repeat across slots — each info/feature slot owns distinct claims.\n\n"
        f"{_reference_photos_note(ctx.product_image_urls)}\n\n"
        f"Images to produce: exactly {quantity} slot(s) of type {name.value} "
        f"(slot 1 through {quantity}). Submit EXACTLY {quantity} plan entries via the tool.\n\n"
        "For EVERY slot, reason it out and decide:\n"
        "- the role/objective for a high-converting, policy-compliant listing in this "
        "marketplace/category, drawn from the image_plan palette (core first) when present;\n"
        "- a DISTINCT concept — no slot may duplicate another;\n"
        "- composition, camera angle, background, props, lighting, styling and visual hierarchy;\n"
        "- honesty: the depiction must NOT contradict the attached real product (its colour, form, "
        "material, finish, pattern) — never render it as something it is not;\n"
        "- physical coherence: show the product realistically and correctly used/placed;\n"
        "- on-image text/badges appropriate to this image role and the marketplace's compliance "
        "rules (a strict primary/main image carries no text or badges; secondary images may) — "
        "shopper-facing only, never A+/EBC/PDP/internal labels;\n"
        "- brand logo: never draw/render a logo or brand wordmark, and never leave reserved "
        "space for one — every slot prompt must state this explicitly; the logo is composited "
        "later in code;\n"
        "- do NOT choose or mention an aspect ratio, canvas shape, orientation or pixel/format "
        "dimensions anywhere — the renderer uses a fixed ratio per image type, so compose for the "
        "subject and leave the canvas shape entirely to the system.\n\n"
        "Keep the whole set LINKED via one shared visual system that MUST incorporate COMMON "
        "IMAGE CONTEXT palette, mood, and category norms so every image clearly belongs to the "
        "same product and brand. Choose typography freely (no Brand DNA font lock-in); never "
        "print font family names on the artwork. Use product facts ONLY from "
        "PRODUCT DATA; if a helpful detail is missing, stay neutral — never fabricate. The real "
        "product reference image(s) are also supplied to the image model at render time.\n\n"
        f"{_RULES}\n\n"
        f"{_category_block(brief)}\n\n"
        f"{common_block}\n\n"
        f"{_product_block(ctx.product)}\n\n"
        "When finished, call the submit_gallery_plan tool with shared_style and exactly "
        f"{quantity} slots entries (type={name.value}, slot=1..{quantity}). Each prompt must be "
        "a complete, standalone image-generation prompt that incorporates the shared_style, "
        "COMMON IMAGE CONTEXT, and every decision above. Do not write the plan as free-form JSON "
        "in the message body."
    )


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
        + (
            f"{image_on_canvas_copy_rules()}\n\n"
            "Preserve these on-image copy rules in the revised prompt unless the user explicitly "
            "requests internal/module labels on the artwork (they should not).\n"
            "If the PREVIOUS PROMPT contains an === COMMON IMAGE CONTEXT === block, preserve "
            "palette/mood/category norms, but do NOT reintroduce or invent named Brand DNA "
            "typefaces. Never instruct the image model to print font family names on the "
            "artwork.\n"
            if data_type == AttributeDataType.IMAGE
            else ""
        )
        + (
            "When finished, call the submit_revised_prompt tool with the final prompt "
            "string — do not write the prompt as free-form JSON in the message body.\n\n"
        )
        + f"PREVIOUS PROMPT:\n{previous_prompt}\n\n"
        + f"{current_block}\n\n"
        + f"USER IMPROVEMENT:\n{improvement.strip()}"
    )
