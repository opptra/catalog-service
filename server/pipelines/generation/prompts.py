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
from pipelines.generation import category, tools
from pipelines.generation.context import GenerationContext

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


def _text_cache_prefix(ctx: GenerationContext) -> str:
    """Shared cacheable prefix for strategy and generation: rules + product + brand."""
    return f"{_RULES}\n\n{_product_block(ctx.product)}\n\n{_brand_block(ctx.brand_dna)}"


def text_strategy_parts(ctx: GenerationContext, names: list[AttributeName]) -> PromptParts:
    """Strategy prompt split for caching: shared product/brand prefix; CI brief last."""
    brief = category.text_brief(ctx.category_intelligence, names)
    attribute_list = ", ".join(name.value for name in names)
    attr_phrase = (
        f"this attribute: {attribute_list}"
        if len(names) == 1
        else f"these attributes: {attribute_list}"
    )
    suffix = (
        "You are an expert marketplace listing strategist. Produce a concise, high-signal "
        f"content strategy for generating {attr_phrase}. Base it on the "
        "Category Intelligence — positioning, differentiators, messaging, high-value keywords "
        "and customer signals (lead with what buyers praise, reassure on what they complain "
        "about). Reference the product only to tailor the angle. Output tight strategy notes in "
        "bullets, NOT final copy.\n\n"
        f"{_category_block(brief)}"
    )
    return PromptParts(prefix=_text_cache_prefix(ctx), suffix=suffix)


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
    """Generation prompt: same cache prefix as strategy; strategy + attribute rules + tool."""
    target = f"the final {names[0].value}" if len(names) == 1 else "the final text attributes"
    rules_block = _attribute_rules_block(names)
    suffix = (
        "You are an expert marketplace copywriter. Using the STRATEGY and the authoritative "
        f"PRODUCT DATA above, write {target}. Apply the Brand DNA voice and "
        "guardrails. Every factual claim must be supported by PRODUCT DATA; when a recommended "
        "detail is missing, adapt gracefully with neutral, high-quality copy rather than "
        "guessing.\n\n"
        + (f"{rules_block}\n\n" if rules_block else "")
        + f"STRATEGY:\n{strategy}\n\n"
        f"{_text_tool_instruction(names)}"
    )
    return PromptParts(prefix=_text_cache_prefix(ctx), suffix=suffix)


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
    return PromptParts(prefix=_text_cache_prefix(ctx), suffix=suffix)


def _product_block(product: dict) -> str:
    # source_assets is dropped from the text block: the images it points to are attached above as
    # actual vision inputs, so repeating their raw URLs here is noise, not signal.
    facts = {key: value for key, value in product.items() if key != "source_assets"}
    return (
        "=== PRODUCT DATA (authoritative — the ONLY source of product facts) ===\n"
        f"{json.dumps(facts, ensure_ascii=False, indent=2)}"
    )


def _category_block(brief: dict) -> str:
    return (
        "=== CATEGORY INTELLIGENCE (how to optimize — NOT a source of product facts) ===\n"
        f"{json.dumps(brief, ensure_ascii=False, indent=2)}"
    )


def _brand_block(brand_dna: str) -> str:
    return f"=== BRAND DNA (voice, personality, guardrails, restricted claims) ===\n{brand_dna}"


def text_regeneration_parts(
    ctx: GenerationContext,
    name: AttributeName,
    *,
    origin_brief: str,
    current_value: str,
    improvement: str,
) -> PromptParts:
    """Regenerate from v1 brief + current copy + this user note. Product/brand are reloaded.

    Does not send full category intelligence — v1 already translated that into the brief.
    Does not stack older user notes; current_value already reflects them.
    """
    rules_block = _attribute_rules_block([name])
    suffix = (
        "You are an expert marketplace copywriter. Regenerate this attribute in place.\n"
        "Keep the ORIGINAL BRIEF as the creative direction. Apply ONLY the REQUESTED CHANGE "
        "to the CURRENT OUTPUT. Leave everything else that still fits the brief unchanged. "
        "Do not invent product facts — PRODUCT DATA is the only source of facts. "
        "Do not rewrite the original brief; produce the new attribute value.\n\n"
        + (f"{rules_block}\n\n" if rules_block else "")
        + f"ORIGINAL BRIEF:\n{origin_brief}\n\n"
        f"CURRENT OUTPUT:\n{current_value}\n\n"
        f"REQUESTED CHANGE:\n{improvement.strip()}\n\n"
        f"{_text_tool_instruction([name])}"
    )
    return PromptParts(prefix=_text_cache_prefix(ctx), suffix=suffix)


def image_regeneration_addendum(*, improvement: str) -> str:
    """User note for regen. v1 brief is separate; photos attach at render time."""
    return f"Requested change:\n{improvement.strip()}"
