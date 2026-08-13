"""Prompt construction. Reasons over three inputs with distinct roles:

- PRODUCT DATA — the ONLY source of product facts (authoritative).
- CATEGORY INTELLIGENCE — how to optimize the listing (strategy, positioning, messaging, image
  concepts); never a source of product facts.
- BRAND DNA — voice, personality, guardrails, restricted claims.

No hardcoded content or image templates: strategy and image direction are derived from the data.
"""

import json
from dataclasses import dataclass

from entities.catalog.attribute_enums import AttributeName
from generation import category, common_image, tools
from generation.context import GenerationContext

# Single source: constraints for copy and branding drawn ON generated listing images.
_IMAGE_RENDER_RULES_MARKER = "=== IMAGE RENDER RULES ==="

_IMAGE_ON_CANVAS_COPY_RULES = (
    "ON-IMAGE COPY (shopper-facing only):\n"
    "- Every headline, badge, and label on the artwork must read as normal product copy a "
    "shopper sees on the live listing.\n"
    "- NEVER render internal or ops jargon on the image — including A+, A Plus, A+ Content, "
    "A+ Features, A+ Care, Enhanced Brand Content, EBC, PDP, gallery slot, IMAGE, A_PLUS, "
    'module names, attribute type codes, or phrases like "A plus module works included".\n'
    "- NEVER render character limits, schema notes, tool instructions, regeneration notes, "
    "or any meta/ops commentary on the artwork.\n"
    "- Planning hints (IMAGE/A_PLUS slots, CI role/kind/pattern codes) are for you only; "
    "translate them into real messaging (e.g. Features, Care instructions, King bed fit) — "
    "never print the hint labels.\n"
    "- Factual size/fit labels are fine when shopper-facing (e.g. King Size, Fits King Bed) — "
    "not prefixed with A+ or module jargon."
)

_IMAGE_LOGO_RULES = (
    "Brand logo: do not draw, render, watermark, or place any brand logo or brand name on the "
    "image. Do not leave empty reserved space, corners, banners, margins, or padding for a logo "
    "— the logo is added later by a deterministic code step."
)

# Shared rules applied to every generation call (text and image planning).
# Per-attribute copy format (pipes, bullet roles, title packing, etc.) comes from
# Category Intelligence playbooks — do not hardcode ATTRIBUTE RULES that fight CI.
_RULES = (
    "RULES:\n"
    "- Product facts (materials, dimensions, colour, pack size, care, weight, etc.) come ONLY "
    "from PRODUCT DATA. Never invent, infer, or import facts from Category Intelligence.\n"
    "- If Category Intelligence recommends a detail that PRODUCT DATA does not contain, omit it "
    "or stay neutral — never fabricate values or make unsupported claims.\n"
    "- Use Category Intelligence for strategy, positioning, messaging, format, differentiators "
    "and keywords; use Brand DNA for tone, personality and restricted claims. Do not let Brand "
    "DNA override category best practices unless a brand guardrail requires it.\n"
    "- Optimize for listing quality, customer trust, marketplace compliance and conversion — "
    "quality over completeness.\n"
    "- NEVER leak instructions into outputs: shopper-facing text and on-image copy must never "
    "include character limits, bounds (e.g. 'upper-bounded at 200'), schema notes, tool names, "
    "prompt rules, regeneration notes, or any other meta/ops commentary."
)


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
        "Category Intelligence — positioning, differentiators, messaging, format "
        "(e.g. pipe-separated highlights when the playbook says so), high-value keywords "
        "and customer signals (lead with what buyers praise, reassure on what they complain "
        "about). Carry format/structure actions from the playbook into the strategy notes. "
        "Reference the product only to tailor the angle. Output tight strategy notes in "
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


def text_generation_parts(
    ctx: GenerationContext, names: list[AttributeName], strategy: str
) -> PromptParts:
    """Generation prompt split for caching: rules + product + brand; strategy/tool last."""
    target = f"the final {names[0].value}" if len(names) == 1 else "the final text attributes"
    prefix = f"{_RULES}\n\n{_product_block(ctx.product)}\n\n{_brand_block(ctx.brand_dna)}"
    suffix = (
        "You are an expert marketplace copywriter. Using the STRATEGY and the authoritative "
        f"PRODUCT DATA below, write {target}. Apply the Brand DNA voice and "
        "guardrails. Follow the STRATEGY for structure and format (including separators such as "
        "pipes when Category Intelligence / strategy specifies them). Every factual claim must "
        "be supported by PRODUCT DATA; when a recommended detail is missing, adapt gracefully "
        "with neutral, high-quality copy rather than guessing.\n\n"
        f"STRATEGY:\n{strategy}\n\n"
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

    Full Brand DNA is NOT included — use ``ctx.common_image_context`` (distilled brand +
    category visual bits) so every plan shares the same typography/palette/norms.
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
            "(missing — still keep one shared typography and palette across every slot)"
        )
    )
    return (
        "You are an expert e-commerce visual merchandiser and product-photography art director. "
        f"Design a COHERENT {type_label} image set for ONE product. Produce EXACTLY {quantity} "
        f"image(s) for internal type {name.value} — count is fixed by the job; do not add, drop, "
        "or replace it with recommended_build. Use COMMON IMAGE CONTEXT and the attached "
        "product image(s) so the set forms one connected, non-redundant series with identical "
        "typefaces.\n\n"
        f"{_IMAGE_ON_CANVAS_COPY_RULES}\n\n"
        "FACT GROUNDING (mandatory — overrides every role/style suggestion below):\n"
        "- PRODUCT DATA is the ONLY source of what this product IS and HAS. Every feature, spec, "
        "benefit, material, colour, size, variant, accessory, included item, or configuration you "
        "depict or label on ANY image MUST be explicitly present in PRODUCT DATA (or plainly "
        "visible in the attached real product photos). If it is not there, do NOT show it, label "
        "it, or imply it.\n"
        "- Depict ONLY this one exact SKU as described in PRODUCT DATA — a single configuration. "
        "Do NOT show alternate colours, sizes, sets, bundles, multi-packs, or 'variant/options' "
        "line-ups unless PRODUCT DATA explicitly lists those variants for THIS item.\n"
        "- Never invent a feature or use-case to make a slot look richer (e.g. adjustability, "
        "extra compartments, modes, certifications). When unsure whether a detail is real, leave "
        "it out.\n\n"
        "ROLE PALETTE (image_plan when present):\n"
        f"- CATEGORY INTELLIGENCE.image_plan.{name.value} is a CATEGORY-GENERIC template of roles "
        "that typical products in this category use — guidance, not a locked recipe, and NOT a "
        "claim that this SKU has those features/variants.\n"
        "- A suggested role is usable ONLY if PRODUCT DATA supports its content. If a role implies "
        "a feature, variant, or claim this SKU does not have (e.g. a variant/colour line-up, a "
        "feature-callout the data lacks), SKIP that role — do not fabricate content to fill it.\n"
        "- Prefer priority=core roles as the main ideas, but drop any core role the data can't "
        "support and pick the next fact-backed one instead.\n"
        "- If there are not enough fact-backed feature/variant roles to reach the required count, "
        "fill the remainder with fact-safe roles that need NO new claims — hero on a clean "
        "background, in-context lifestyle use, true-to-spec scale/dimension (using real dimensions "
        "from PRODUCT DATA), material/texture macro, real construction detail, or accurate "
        "packaging / what's-in-the-box (only genuinely included items). Differentiate by "
        "composition, never by invented facts.\n"
        "- Do NOT copy CI text verbatim onto the image; translate role/kind/pattern/content into "
        "a concrete render prompt for THIS product + COMMON IMAGE CONTEXT.\n"
        "- Topic playbook is supporting context only; image_plan is the primary role guidance "
        "when present — but always subordinate to FACT GROUNDING above.\n\n"
        "NON-REDUNDANCY (mandatory):\n"
        "- Every slot must have a clearly different role and visual concept.\n"
        "- No two slots may look like the same shot with minor tweaks (same angle, setting, "
        "info density, or lifestyle framing).\n"
        "- Make the difference obvious in composition, camera, background, props, and on-image "
        "information load; each concept field must name a distinct role.\n"
        "- Differentiate slots by ROLE and COMPOSITION. When the number of fact-backed claims is "
        "smaller than the slot count, do NOT invent claims to force distinctness — repeat no "
        "fabricated facts, and make the remaining slots distinct through fact-free composition "
        "instead.\n\n"
        f"{_reference_photos_note(ctx.product_image_urls)}\n\n"
        f"Images to produce: exactly {quantity} slot(s) of type {name.value} "
        f"(slot 1 through {quantity}). Submit EXACTLY {quantity} plan entries via the tool.\n\n"
        "For EVERY slot, reason it out and decide:\n"
        "- the role/objective for a high-converting, policy-compliant listing in this "
        "marketplace/category, drawn from the image_plan palette (core first) when present;\n"
        "- a DISTINCT concept — no slot may duplicate another;\n"
        "- composition, camera angle, background, props, lighting, styling and visual hierarchy;\n"
        "- honesty: the depiction must NOT contradict the attached real product (its colour, form, "
        "material, finish, pattern) AND must not add any feature, variant, colour, size, or "
        "accessory that PRODUCT DATA does not list — never render it as something it is not, and "
        "never enrich it with details the data does not support;\n"
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
        "IMAGE CONTEXT typography (primary ± secondary), palette, mood, and category norms so "
        "every image clearly belongs to the same product and brand. Use product facts ONLY from "
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


def strip_user_edit(prompt: str) -> str:
    """Return the stored brief without a trailing USER EDIT block."""
    marker = "=== USER EDIT ==="
    if marker not in prompt:
        return prompt.rstrip()
    head, _sep, _tail = prompt.partition(marker)
    return head.rstrip()


def prompt_with_user_edit(previous_prompt: str, improvement: str) -> str:
    """Persist the original brief plus the user's edit note (no rewritten prompt)."""
    note = improvement.strip()
    base = strip_user_edit(previous_prompt)
    if not note:
        return base
    return f"{base}\n\n=== USER EDIT ===\n{note}"


def regeneration_text_prompt(
    *,
    attribute_name: AttributeName,
    previous_prompt: str,
    current_value: str,
    improvement: str,
) -> str:
    """One-shot text regen: keep the original brief, apply the user note to the current value."""
    brief = strip_user_edit(previous_prompt)
    return (
        f"You are regenerating marketplace text for attribute {attribute_name.value}.\n"
        "Use the PREVIOUS PROMPT as the full brief (category structure, brand voice, packing "
        "order, constraints). Do NOT invent a new brief and do NOT rewrite the previous prompt.\n"
        "Start from CURRENT OUTPUT. Apply ONLY the USER IMPROVEMENT. Keep every other word, "
        "fact, and ordering unless changing it is required to satisfy the improvement.\n"
        "Do not invent product facts. The result must differ from CURRENT OUTPUT whenever the "
        "improvement asks for a visible change (spacing, wording, punctuation, structure).\n"
        "Write complete, natural copy — do not cut mid-word or mid-phrase. "
        "When finished, call the submit_text_attributes tool with the updated value — "
        "do not write free-form JSON in the message body.\n\n"
        f"PREVIOUS PROMPT:\n{brief}\n\n"
        f"CURRENT OUTPUT:\n{current_value}\n\n"
        f"USER IMPROVEMENT:\n{improvement.strip()}"
    )


def text_length_correction(
    attribute_name: AttributeName,
    current_value: str,
    instructions: list[str],
    *,
    is_list: bool,
) -> str:
    """Feedback note appended on a length-retry.

    ``instructions`` are concrete per-string cut targets (e.g. "item 3: 262 chars — remove
    at least 62 to get under 200; aim for ≤180"). For list attributes the model must change
    ONLY the flagged items and return the others unchanged, so passing items never regress.
    """
    instruction_lines = "\n".join(f"- {line}" for line in instructions)
    if is_list:
        scope = (
            "Return the FULL array. Change ONLY the flagged items below; copy every other item "
            "EXACTLY as it is now. For each flagged item, shorten it to the target."
        )
    else:
        scope = "Shorten the value to the target below."
    return (
        "LENGTH CORRECTION: some copy is over the character maximum. "
        f"{scope}\n"
        "Keep the same meaning, facts, tone, and structure; compress or drop the least "
        "important words. Every value/item must end on a complete word — never cut mid-word "
        "or mid-phrase, never pad with filler, and do not invent product facts.\n\n"
        f"FIX THESE:\n{instruction_lines}\n\n"
        f"CURRENT OUTPUT:\n{current_value}\n\n"
        "Call the submit_text_attributes tool with the corrected value."
    )


def regeneration_image_prompt(
    *,
    attribute_name: AttributeName,
    previous_prompt: str,
    improvement: str,
) -> str:
    """One-shot image regen: keep the original brief; current output is attached as reference."""
    brief = strip_user_edit(previous_prompt)
    return (
        f"You are regenerating marketplace image attribute {attribute_name.value}.\n"
        "Use the PREVIOUS PROMPT as the full brief (composition, on-canvas copy, style, "
        "category norms). Do NOT invent a replacement brief.\n"
        "The first attached reference image is CURRENT OUTPUT — improve that image. "
        "Apply ONLY the USER IMPROVEMENT. Preserve product identity and everything the user "
        "did not ask to change. Remaining references are real product photos (colour/shape/"
        "material truth).\n"
        f"{image_on_canvas_copy_rules()}\n"
        "If PREVIOUS PROMPT contains === COMMON IMAGE CONTEXT ===, honour it unless the user "
        "explicitly asks to change visual style or fonts.\n\n"
        f"PREVIOUS PROMPT:\n{brief}\n\n"
        f"USER IMPROVEMENT:\n{improvement.strip()}"
    )
