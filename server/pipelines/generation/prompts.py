"""Prompt construction for text generation.

Text uses two inputs with distinct roles:
- FACT SHEET — the ONLY source of product facts (``facts_for_sku`` / ``GenerationContext.product``).
- CATEGORY INTELLIGENCE topic — craft only (structure, positioning); never a source of facts.

Backend keywords are a filter of CI ``backend_keywords.terms`` against the fact sheet.
Brand DNA is for images only (fonts/colors), not sent on text calls.
"""

import json
from dataclasses import dataclass
from typing import Any

from entities.catalog.attribute_enums import AttributeName
from pipelines.generation import category, tools
from pipelines.generation.context import GenerationContext

_TEXT_RULES = (
    "RULES:\n"
    "- Product facts (materials, dimensions, colour, pack size, care, weight, etc.) come ONLY "
    "from the FACT SHEET. Never invent, infer, or import facts from Category Intelligence.\n"
    "- Category Intelligence below is craft only — how to structure and optimize copy. If it "
    "recommends a detail the FACT SHEET does not contain, omit it.\n"
    "- Optimize for listing quality, customer trust, marketplace compliance and conversion — "
    "quality over completeness."
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


def _text_cache_prefix(ctx: GenerationContext) -> str:
    """Shared cacheable prefix for text: rules + fact sheet only."""
    return f"{_TEXT_RULES}\n\n{_fact_sheet_block(ctx.product)}"


def craft_v1_brief(ctx: GenerationContext, name: AttributeName) -> str:
    """Persisted v1 brief for regen — category craft snapshot for this attribute."""
    craft = category.text_craft_brief(ctx.category_intelligence, name)
    return _craft_block(craft)


def _text_tool_instruction(names: list[AttributeName]) -> str:
    """Tool-call instruction listing only the requested attributes and their types."""
    keys = ", ".join(name.value for name in names)
    field_word = "field" if len(names) == 1 else "fields"
    type_lines: list[str] = []
    for attr_name in names:
        if attr_name in tools.LIST_TEXT_ATTRIBUTES:
            type_lines.append(f'"{attr_name.value}" must be an array of strings.')
        else:
            type_lines.append(f'"{attr_name.value}" must be a string.')
    type_note = " ".join(type_lines)
    return (
        f"When finished, call the submit_text_attributes tool with exactly "
        f"{'this' if len(names) == 1 else 'these'} {field_word}: {keys}. "
        f"{type_note} Do not write the attribute"
        f"{'' if len(names) == 1 else 's'} as free-form JSON in the message body."
    )


def text_generation_parts(ctx: GenerationContext, name: AttributeName) -> PromptParts:
    """Generation prompt: fact sheet prefix; craft topic + tool instruction in suffix."""
    suffix = (
        "You are an expert marketplace copywriter. Using the CATEGORY CRAFT and the FACT SHEET "
        f"above, write the final {name.value}. Every factual claim must be supported by the "
        "FACT SHEET; when craft recommends a detail the fact sheet lacks, adapt gracefully "
        "with neutral, high-quality copy rather than guessing.\n\n"
        f"{craft_v1_brief(ctx, name)}\n\n"
        f"{_text_tool_instruction([name])}"
    )
    return PromptParts(prefix=_text_cache_prefix(ctx), suffix=suffix)


def keyword_filter_parts(
    ctx: GenerationContext,
    *,
    candidates: dict[str, Any],
    candidate_terms: list[str],
) -> PromptParts:
    """Filter merged CI backend keyword candidates against the fact sheet."""
    byte_limit = candidates.get("marketplace_limit_bytes")
    limit_note = ""
    if isinstance(byte_limit, int) and byte_limit > 0:
        limit_note = (
            f"\nWhen joined with spaces the kept terms must fit within {byte_limit} bytes "
            "(UTF-8). Prefer fewer terms over paraphrasing.\n"
        )
    suffix = (
        "You filter Amazon backend search-term candidates for this SKU.\n"
        "RULES:\n"
        "- Return ONLY terms from CANDIDATE TERMS below — exact strings, same spelling.\n"
        "- Do not invent, paraphrase, or add new terms.\n"
        "- KEEP a term when the FACT SHEET supports the feature/material/spec it asserts, "
        "OR when it is vernacular/use-case/search language that does NOT assert a missing spec "
        "(e.g. room type, regional word).\n"
        "- DROP a term when it claims a feature, material, or spec the FACT SHEET lacks or "
        "contradicts.\n"
        "- Duplicating words already used in the title or other visible copy is fine.\n"
        f"{limit_note}\n"
        f"CANDIDATE TERMS:\n{json.dumps(candidate_terms, ensure_ascii=False, indent=2)}\n\n"
        "When finished, call the filter_backend_keywords tool with the kept terms in your "
        "preferred order."
    )
    return PromptParts(prefix=_text_cache_prefix(ctx), suffix=suffix)


def key_features_parts(
    ctx: GenerationContext, *, description: str, bullet_points: list[str]
) -> PromptParts:
    """KEY_FEATURES: condense already-written Description + Bullet Points (no CI topic)."""
    name = AttributeName.KEY_FEATURES
    bullets_block = "\n".join(f"- {bullet}" for bullet in bullet_points)
    suffix = (
        "You are an expert marketplace copywriter. Write Amazon's KEY PRODUCT FEATURES "
        "field: five short standalone feature phrases (not full sentences), one per line "
        "slot. Condense and rephrase the ALREADY-WRITTEN Bullet Points and Description "
        "below — do not introduce any fact that is not in them or in the FACT SHEET, and do "
        "not simply copy a bullet verbatim.\n\n"
        f"ALREADY-WRITTEN BULLET POINTS:\n{bullets_block}\n\n"
        f"ALREADY-WRITTEN DESCRIPTION:\n{description}\n\n"
        f"{_text_tool_instruction([name])}"
    )
    return PromptParts(prefix=_text_cache_prefix(ctx), suffix=suffix)


def _fact_sheet_block(product: dict) -> str:
    facts = {key: value for key, value in product.items() if key != "source_assets"}
    return (
        "=== FACT SHEET (authoritative — the ONLY source of product facts) ===\n"
        f"{json.dumps(facts, ensure_ascii=False, indent=2)}"
    )


def _craft_block(craft: dict) -> str:
    return (
        "=== CATEGORY CRAFT (structure and positioning — NOT a source of product facts) ===\n"
        f"{json.dumps(craft, ensure_ascii=False, indent=2)}"
    )


def text_regeneration_parts(
    ctx: GenerationContext,
    name: AttributeName,
    *,
    origin_brief: str,
    current_value: str,
    improvement: str,
) -> PromptParts:
    """Regenerate from v1 brief + current copy + this user note."""
    suffix = (
        "You are an expert marketplace copywriter. Regenerate this attribute in place.\n"
        "Keep the ORIGINAL BRIEF (category craft for this field) as the creative direction. "
        "Apply ONLY the REQUESTED CHANGE "
        "to the CURRENT OUTPUT. Leave everything else that still fits the brief unchanged. "
        "Do not invent product facts — the FACT SHEET is the only source of facts. "
        "Do not rewrite the original brief; produce the new attribute value.\n\n"
        f"ORIGINAL BRIEF:\n{origin_brief}\n\n"
        f"CURRENT OUTPUT:\n{current_value}\n\n"
        f"REQUESTED CHANGE:\n{improvement.strip()}\n\n"
        f"{_text_tool_instruction([name])}"
    )
    return PromptParts(prefix=_text_cache_prefix(ctx), suffix=suffix)


def image_regeneration_addendum(*, improvement: str) -> str:
    """User note for regen. v1 brief is separate; photos attach at render time."""
    return f"Requested change:\n{improvement.strip()}"
