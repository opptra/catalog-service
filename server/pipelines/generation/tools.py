"""OpenRouter tool schemas for structured generation outputs.

JSON results are collected via forced tool calls (not free-form JSON in the
assistant message). The tool is never executed — its ``arguments`` *are* the
structured payload we want.
"""

import re
from dataclasses import dataclass
from typing import Any

from entities.catalog.attribute_enums import AttributeName

GALLERY_FACT_BOARD_TOOL_NAME = "submit_fact_board"
TEXT_ATTRIBUTES_TOOL_NAME = "submit_text_attributes"
COMPRESSED_BRAND_DNA_TOOL_NAME = "submit_compressed_brand_dna"


def gallery_fact_board_tool() -> dict[str, Any]:
    """Tool schema for binding CI claims to zero or more verified PRODUCT DATA snippets.

    Combined claims (e.g. cover and pillow dimensions) may emit one entry per independent
    spec that exists on this SKU. Undeterminable claims emit nothing.
    """
    return {
        "type": "function",
        "function": {
            "name": GALLERY_FACT_BOARD_TOOL_NAME,
            "description": (
                "Return verified product snippets for the requested feature-priority claims. "
                "Each claim may yield zero or more items. Never invent. Prefer short structured "
                "fields. For combined claims that name independent specs, emit one item per "
                "spec that actually exists on this SKU."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "facts": {
                        "type": "array",
                        "description": (
                            "Zero or more snippets. Same claim may appear more than once when "
                            "it names independent specs (e.g. cover size and pillow size)."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "claim": {
                                    "type": "string",
                                    "description": (
                                        "The feature-priority claim string, copied exactly."
                                    ),
                                },
                                "value": {
                                    "type": "string",
                                    "description": (
                                        "Short verbatim snippet copied from the source field "
                                        "(not the whole marketing paragraph when a shorter "
                                        "supporting phrase exists)."
                                    ),
                                },
                                "source_field": {
                                    "type": "string",
                                    "description": (
                                        "Exact PRODUCT DATA key the value was copied from."
                                    ),
                                },
                            },
                            "required": ["claim", "value", "source_field"],
                            "additionalProperties": False,
                        },
                        "minItems": 0,
                    }
                },
                "required": ["facts"],
                "additionalProperties": False,
            },
        },
    }


COMPRESSED_BRAND_DNA_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": COMPRESSED_BRAND_DNA_TOOL_NAME,
        "description": (
            "Submit a minimal JSON DNA of this brand's visual styling, reused for every "
            "image in this job. Copy fonts and colors from the source; do not invent."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "fonts": {
                    "type": "object",
                    "description": "Typefaces named in Brand DNA. Omit a key if the source has none.",
                    "properties": {
                        "headline": {
                            "type": "string",
                            "description": "Primary / headline typeface name only.",
                        },
                        "body": {
                            "type": "string",
                            "description": "Secondary / body typeface name only.",
                        },
                        "dimension": {
                            "type": "string",
                            "description": "Measurement overlay typeface name only.",
                        },
                    },
                    "additionalProperties": False,
                },
                "colors": {
                    "type": "object",
                    "description": "Brand palette as named in Brand DNA.",
                    "properties": {
                        "primary": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Primary brand colors (hex and/or name).",
                        },
                        "secondary": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Secondary brand colors (hex and/or name).",
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["fonts", "colors"],
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
