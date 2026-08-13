"""OpenRouter tool schemas for structured generation outputs.

JSON results are collected via forced tool calls (not free-form JSON in the
assistant message). The tool is never executed — its ``arguments`` *are* the
structured payload we want.
"""

from dataclasses import dataclass
from typing import Any

from entities.catalog.attribute_enums import AttributeName

GALLERY_PLAN_TOOL_NAME = "submit_gallery_plan"
TEXT_ATTRIBUTES_TOOL_NAME = "submit_text_attributes"
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


# --- Amazon text-attribute limits (single source of truth) --------------------
#
# Character maximums are Amazon caps. They are enforced in CODE, never as JSON
# schema ``maxLength``: constrained decoding treats ``maxLength`` as advisory and
# tends to close the string early, causing mid-word cuts (e.g. "…Insu"). The
# schema only fixes SHAPE (fields, types, item counts); length is validated after
# the call and, if exceeded, corrected via a bounded feedback retry (see
# ``generation.text.submit_text_attribute``). Never deterministically truncate copy.
#
# Soft minimums are description-only guidance (never JSON ``minLength``).
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


# Amazon marketplace limits (title policy effective 2026-07-27).
TEXT_LIMITS: dict[AttributeName, TextLimit] = {
    AttributeName.TITLE: TextLimit(max_chars=75, min_chars=60),
    AttributeName.ITEM_HIGHLIGHTS: TextLimit(max_chars=125, min_chars=100),
    AttributeName.BULLET_POINTS: TextLimit(
        item_count=5, per_item_max_chars=200, per_item_min_chars=120
    ),
    AttributeName.KEY_FEATURES: TextLimit(
        item_count=5, per_item_max_chars=100, per_item_min_chars=40
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


@dataclass(frozen=True, slots=True)
class LengthIssue:
    """One over-limit string. ``index`` is the 0-based list position, or None for a scalar."""

    index: int | None
    length: int
    max_chars: int

    @property
    def excess(self) -> int:
        return self.length - self.max_chars


def over_limit_report(name: AttributeName, value: Any) -> list[LengthIssue]:
    """Structured over-cap report used by the length-correction loop (empty if within caps)."""
    limit = TEXT_LIMITS.get(name)
    if limit is None:
        return []

    issues: list[LengthIssue] = []
    if name in LIST_TEXT_ATTRIBUTES:
        if not isinstance(value, list) or limit.per_item_max_chars is None:
            return []
        for index, item in enumerate(value):
            length = len("" if item is None else str(item))
            if length > limit.per_item_max_chars:
                issues.append(
                    LengthIssue(index=index, length=length, max_chars=limit.per_item_max_chars)
                )
        return issues

    if limit.max_chars is None:
        return []
    length = len("" if value is None else str(value))
    if length > limit.max_chars:
        issues.append(LengthIssue(index=None, length=length, max_chars=limit.max_chars))
    return issues


def char_limit_violations(name: AttributeName, value: Any) -> list[str]:
    """Human-readable hard-max character violations (empty if within caps)."""
    if name in LIST_TEXT_ATTRIBUTES and not isinstance(value, list):
        return [f"{name.value} must be an array of strings"]
    violations: list[str] = []
    for issue in over_limit_report(name, value):
        if issue.index is None:
            violations.append(f"{issue.length} characters (HARD MAX {issue.max_chars})")
        else:
            violations.append(
                f"item {issue.index + 1}: {issue.length} characters "
                f"(HARD MAX {issue.max_chars})"
            )
    return violations


def _limit_description(limit: TextLimit) -> str:
    """Human-readable limit summary embedded in the tool property description.

    Character maximums are stated as instructions (not schema ``maxLength``) so the
    model aims for them without the decoder forcing a mid-word cut.
    """
    parts: list[str] = []
    if limit.max_chars is not None:
        parts.append(f"at most {limit.max_chars} characters including spaces")
        if limit.min_chars is not None:
            parts.append(f"soft target around {limit.min_chars}+ when real facts support it")
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
        parts.append(f"each item at most {limit.per_item_max_chars} characters including spaces")
        if limit.per_item_min_chars is not None:
            parts.append(
                f"each item soft target around {limit.per_item_min_chars}+ when "
                "real facts support it"
            )
    if not parts:
        return ""
    return (
        "LIMITS: "
        + "; ".join(parts)
        + ". Stay within the character maximum AND finish on a complete word — never cut "
        "mid-word or mid-phrase, never pad with filler, and never mention character counts, "
        "bounds, schema notes, or these instructions in the output value."
    )


def _text_property_schema(name: AttributeName) -> dict[str, Any]:
    """JSON-schema property for one text attribute.

    Shape only: types + item counts. Character maximums live in the description and
    are enforced in code — never as ``maxLength`` (avoids constrained-decoding mid-word cuts).
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
    schema = {"type": "string", "description": description}
    if limit is not None:
        limit_note = _limit_description(limit)
        if limit_note:
            schema["description"] = f"{description} {limit_note}"
    return schema


def text_attributes_tool(names: list[AttributeName]) -> dict[str, Any]:
    """Tool schema whose arguments are exactly the requested text attributes.

    ``strict: true`` constrains SHAPE (fields, types, item counts) on OpenAI-compatible
    providers. Character maximums are NOT schema ``maxLength`` — they are validated in
    code and corrected via a bounded feedback retry.
    """
    properties: dict[str, Any] = {name.value: _text_property_schema(name) for name in names}
    return {
        "type": "function",
        "function": {
            "name": TEXT_ATTRIBUTES_TOOL_NAME,
            "strict": True,
            "description": (
                "Submit the final marketplace text attributes for shoppers. "
                "Values must be clean listing copy only — never include character limits, "
                "schema notes, tool instructions, or meta commentary. "
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
