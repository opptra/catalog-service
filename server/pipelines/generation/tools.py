"""OpenRouter tool schemas for structured generation outputs.

JSON results are collected via forced tool calls (not free-form JSON in the
assistant message). The tool is never executed — its ``arguments`` *are* the
structured payload we want.
"""

import re
from dataclasses import dataclass
from typing import Any

from entities.catalog.attribute_enums import AttributeName

GALLERY_PLAN_TOOL_NAME = "submit_gallery_plan"
TEXT_ATTRIBUTES_TOOL_NAME = "submit_text_attributes"
REVISE_PROMPT_TOOL_NAME = "submit_revised_prompt"
COMMON_IMAGE_CONTEXT_TOOL_NAME = "submit_common_image_context"


def gallery_plan_tool(name: AttributeName, quantity: int) -> dict[str, Any]:
    """Tool schema for one image attribute plan with an exact slot count from the UI job.

    ``slots`` is locked to ``quantity`` items (minItems = maxItems). ``type`` is locked to
    ``name`` so IMAGE and A_PLUS are planned in separate calls.
    """
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    return {
        "type": "function",
        "function": {
            "name": GALLERY_PLAN_TOOL_NAME,
            "description": (
                f"Submit the coherent {name.value} image plan with exactly {quantity} slot(s). "
                "Call this tool with the final plan — do not write the plan as free-form JSON text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "shared_style": {
                        "type": "string",
                        "description": (
                            "One paragraph: the visual system linking every image — must honor "
                            "COMMON IMAGE CONTEXT typography (primary ± secondary), palette, "
                            "mood, and category visual norms; also cover product rendering and "
                            "lighting. Do not invent alternate typefaces."
                        ),
                    },
                    "slots": {
                        "type": "array",
                        "description": (
                            f"Exactly {quantity} entries for type {name.value}, "
                            f"slots 1 through {quantity}."
                        ),
                        "minItems": quantity,
                        "maxItems": quantity,
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": [name.value],
                                    "description": f"Must be {name.value}.",
                                },
                                "slot": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": quantity,
                                    "description": (f"1-based slot index from 1 to {quantity}."),
                                },
                                "concept": {
                                    "type": "string",
                                    "description": "Short label for this slot's distinct concept.",
                                },
                                "prompt": {
                                    "type": "string",
                                    "description": (
                                        "Complete standalone image-generation prompt for this slot."
                                    ),
                                },
                            },
                            "required": ["type", "slot", "prompt"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["shared_style", "slots"],
                "additionalProperties": False,
            },
        },
    }


REVISE_PROMPT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": REVISE_PROMPT_TOOL_NAME,
        "description": (
            "Submit the revised generation prompt after applying the user's improvement notes. "
            "Call this tool with the final prompt — do not write it as free-form JSON text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        "Complete standalone generation prompt that incorporates the previous "
                        "prompt and the user's requested changes."
                    ),
                },
            },
            "required": ["prompt"],
            "additionalProperties": False,
        },
    },
}

COMMON_IMAGE_CONTEXT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": COMMON_IMAGE_CONTEXT_TOOL_NAME,
        "description": (
            "Submit the compact common image context for every image in this job. "
            "Call this tool with the extracted JSON — do not write free-form JSON text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "typography": {
                    "type": "object",
                    "description": "Resolved typefaces for the whole image set.",
                    "properties": {
                        "primary": {
                            "type": "string",
                            "description": "Single primary typeface for titles/headlines.",
                        },
                        "secondary": {
                            "type": "string",
                            "description": "Optional secondary typeface for labels/body.",
                        },
                        "usage": {
                            "type": "string",
                            "description": (
                                "Fixed hierarchy, e.g. titles=primary; labels=secondary."
                            ),
                        },
                    },
                    "required": ["primary"],
                    "additionalProperties": False,
                },
                "palette": {
                    "type": "object",
                    "description": "Brand palette accents useful for pixels.",
                    "properties": {
                        "primary": {"type": "string"},
                        "secondary": {"type": "string"},
                        "accents": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "mood": {
                    "type": "string",
                    "description": "Photography/mood summary for all slots.",
                },
                "visual_guardrails": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Do-nots that affect image pixels.",
                },
                "category": {
                    "type": "object",
                    "description": "Cross-slot category visual norms (not per-slot briefs).",
                    "properties": {
                        "visual_norms": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "on_image_text": {
                            "type": "string",
                            "description": (
                                "Phone-readable / minimal SEO keyword rules for on-image copy."
                            ),
                        },
                        "shared_product_cues": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["typography", "mood", "category"],
            "additionalProperties": False,
        },
    },
}


# --- Amazon text-attribute limits ----------------------------------------------
#
# Soft targets live in tool property descriptions (and attribute guidance).
# Character minLength/maxLength are NOT put on the JSON schema — models often
# stuff to hit a min, then get cut mid-phrase by maxLength. Item counts
# (minItems/maxItems) stay on the schema.
#
# TEMPORARY: ``strip_incomplete_text_ending`` (+ optional char fit) runs after the
# tool returns. Incomplete endings under the ceiling (e.g. "…, White &") are the
# real pain; replace with structured title/highlight parts assembled in code.
#
# ``item_count`` means exactly N items (minItems = maxItems = N).
# ``min_items`` / ``max_items`` allow a range (e.g. backend keywords 10–15).


@dataclass(frozen=True, slots=True)
class TextLimit:
    max_chars: int | None = None
    min_chars: int | None = None
    item_count: int | None = None
    min_items: int | None = None
    max_items: int | None = None
    per_item_max_chars: int | None = None
    per_item_min_chars: int | None = None


# Amazon marketplace hard caps (title policy effective 2026-07-27).
# ``min_chars`` / ``per_item_min_chars`` are soft aims for the model only.
TEXT_LIMITS: dict[AttributeName, TextLimit] = {
    AttributeName.TITLE: TextLimit(max_chars=75, min_chars=60),
    AttributeName.ITEM_HIGHLIGHTS: TextLimit(max_chars=125, min_chars=100),
    AttributeName.BULLET_POINTS: TextLimit(
        item_count=5, per_item_max_chars=200, per_item_min_chars=180
    ),
    AttributeName.KEY_FEATURES: TextLimit(
        item_count=5, per_item_max_chars=100, per_item_min_chars=80
    ),
    AttributeName.BACKEND_KEYWORDS: TextLimit(min_items=10, max_items=15),
}

# Attributes whose value is a list of strings (schema + persistence).
LIST_TEXT_ATTRIBUTES = frozenset(
    {
        AttributeName.BULLET_POINTS,
        AttributeName.KEY_FEATURES,
        AttributeName.BACKEND_KEYWORDS,
    }
)

# Prefer cutting at these separators (longest / most structural first).
_FIT_SEPARATORS: tuple[str, ...] = (" | ", " – ", " — ", " - ", "; ", ", ", " ")

# Trailing junk that means the model stopped mid-phrase (e.g. "…, White &").
_TRAILING_PUNCT_RE = re.compile(r"[\s,;|:\-–—&]+$")
_TRAILING_CONNECTOR_WORD_RE = re.compile(
    r"\s+(?:and|or|with|for|of|the|a|an)\s*$",
    re.IGNORECASE,
)
# Incomplete color/pair clause: "…, White &" / "… | Blue and"
_INCOMPLETE_PAIR_TAIL_RE = re.compile(
    r"(?:,\s*|\s+\|\s+)[^,|]+?\s*(?:&|and|or)\s*$",
    re.IGNORECASE,
)


def strip_incomplete_text_ending(text: str) -> str:
    """Remove dangling mid-phrase endings (e.g. trailing ``&`` / ``and`` / ``,``).

    TEMPORARY safety net only — do not treat this as the long-term fix. Models still
    emit incomplete titles/highlights under the char ceiling (e.g.
    ``…Pillow Covers, White &``). Replace with structured parts (brand / product /
    size / color / …) assembled in code so each fact is included whole or dropped.
    Until that lands, strip the broken tail so we never persist obviously unfinished copy.
    """
    cleaned = text.strip()
    if not cleaned:
        return cleaned

    # Drop an incomplete trailing pair clause first ("…, White &" → "…").
    without_pair = _INCOMPLETE_PAIR_TAIL_RE.sub("", cleaned).rstrip()
    if without_pair != cleaned:
        cleaned = without_pair

    # Then peel leftover dangling punctuation / connector words.
    while True:
        next_text = _TRAILING_PUNCT_RE.sub("", cleaned)
        next_text = _TRAILING_CONNECTOR_WORD_RE.sub("", next_text).strip()
        if next_text == cleaned:
            break
        cleaned = next_text
    return cleaned


def fit_text_to_char_limit(text: str, max_chars: int) -> str:
    """Trim ``text`` to ``max_chars`` at a phrase/word boundary — never mid-word.

    Drops trailing fragments at ``|`` / comma / space rather than ellipsizing.
    Chooses the longest clean cut within the budget. No-op when already in limit.
    """
    cleaned = text.strip()
    if max_chars < 1 or len(cleaned) <= max_chars:
        return cleaned

    window = cleaned[:max_chars]
    # Refuse collapsing to a stub — keep at least half the budget when possible.
    min_keep = max(1, max_chars // 2)
    best = ""
    for sep in _FIT_SEPARATORS:
        idx = window.rfind(sep)
        if idx < min_keep:
            continue
        candidate = window[:idx].rstrip(" \t,;|:-–—")
        if len(candidate) > len(best):
            best = candidate
    if best:
        return best
    return window.rstrip(" \t,;|:-–—")


def apply_text_limits(name: AttributeName, value: Any) -> Any:
    """Post-process one tool-returned text attribute (no LLM retries)."""
    limit = TEXT_LIMITS.get(name)

    if name in LIST_TEXT_ATTRIBUTES:
        if not isinstance(value, list):
            return value
        per_max = limit.per_item_max_chars if limit is not None else None
        out: list[Any] = []
        for item in value:
            if item is None:
                out.append(item)
                continue
            text = strip_incomplete_text_ending(str(item))
            if per_max is not None:
                text = fit_text_to_char_limit(text, per_max)
                text = strip_incomplete_text_ending(text)
            out.append(text)
        return out

    text = strip_incomplete_text_ending(str(value))
    if limit is not None and limit.max_chars is not None:
        text = fit_text_to_char_limit(text, limit.max_chars)
        # Length fit can reintroduce a dangling connector — strip again.
        text = strip_incomplete_text_ending(text)
    return text


def _limit_description(limit: TextLimit) -> str:
    """Soft length guidance embedded in the tool property description."""
    parts: list[str] = []
    if limit.max_chars is not None:
        soft_aim = max(1, limit.max_chars - 3)
        if limit.min_chars is not None:
            parts.append(
                f"aim for about {limit.min_chars}–{soft_aim} characters including spaces "
                f"(hard ceiling {limit.max_chars}; never exceed it)"
            )
        else:
            parts.append(
                f"aim just under {limit.max_chars} characters including spaces "
                f"(hard ceiling {limit.max_chars})"
            )
    if limit.item_count is not None:
        parts.append(f"exactly {limit.item_count} items")
    elif limit.min_items is not None or limit.max_items is not None:
        if limit.min_items is not None and limit.max_items is not None:
            if limit.min_items == limit.max_items:
                parts.append(f"exactly {limit.min_items} items")
            else:
                parts.append(f"between {limit.min_items} and {limit.max_items} items")
        elif limit.max_items is not None:
            parts.append(f"at most {limit.max_items} items")
        else:
            parts.append(f"at least {limit.min_items} items")
    if limit.per_item_max_chars is not None:
        soft_item = max(1, limit.per_item_max_chars - 5)
        if limit.per_item_min_chars is not None:
            parts.append(
                f"each item about {limit.per_item_min_chars}–{soft_item} characters "
                f"(hard ceiling {limit.per_item_max_chars} per item)"
            )
        else:
            parts.append(f"each item at most {limit.per_item_max_chars} characters")
    if not parts:
        return ""
    return (
        "LENGTH: "
        + "; ".join(parts)
        + ". Prefer a finished natural phrase under the ceiling — drop a trailing "
        "segment rather than truncating mid-word or mid-phrase."
    )


def _text_property_schema(name: AttributeName) -> dict[str, Any]:
    """JSON-schema property for one text attribute.

    Item counts are schema-enforced. Character ceilings are soft (description only);
    ``apply_text_limits`` fits oversize strings after the tool returns.
    """
    limit = TEXT_LIMITS.get(name)
    if name in LIST_TEXT_ATTRIBUTES:
        items: dict[str, Any] = {"type": "string"}
        if name == AttributeName.BACKEND_KEYWORDS:
            description = (
                f"{name.value} as an array of search-term strings "
                "(one term or short phrase per item; no commas inside an item)."
            )
        else:
            description = f"{name.value} as an array of strings."
        schema: dict[str, Any] = {
            "type": "array",
            "items": items,
            "description": description,
        }
        if limit is not None:
            limit_note = _limit_description(limit)
            if limit_note:
                schema["description"] = f"{description} {limit_note}"
            if limit.item_count is not None:
                schema["minItems"] = limit.item_count
                schema["maxItems"] = limit.item_count
            else:
                if limit.min_items is not None:
                    schema["minItems"] = limit.min_items
                if limit.max_items is not None:
                    schema["maxItems"] = limit.max_items
        return schema

    description = f"Final copy for {name.value}."
    schema: dict[str, Any] = {"type": "string", "description": description}
    if limit is not None:
        limit_note = _limit_description(limit)
        if limit_note:
            schema["description"] = f"{description} {limit_note}"
    return schema


def text_attributes_tool(names: list[AttributeName]) -> dict[str, Any]:
    """Tool schema whose arguments are exactly the requested text attributes."""
    properties: dict[str, Any] = {name.value: _text_property_schema(name) for name in names}
    return {
        "type": "function",
        "function": {
            "name": TEXT_ATTRIBUTES_TOOL_NAME,
            "description": (
                "Submit the final marketplace text attributes. "
                "Call this tool with the finished copy — do not write JSON in the message body."
            ),
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": [name.value for name in names],
                "additionalProperties": False,
            },
        },
    }
