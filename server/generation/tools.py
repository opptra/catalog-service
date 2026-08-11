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
REVISE_PROMPT_TOOL_NAME = "submit_revised_prompt"

GALLERY_PLAN_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": GALLERY_PLAN_TOOL_NAME,
        "description": (
            "Submit the coherent image-gallery plan for every requested slot. "
            "Call this tool with the final plan — do not write the plan as free-form JSON text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "shared_style": {
                    "type": "string",
                    "description": (
                        "One paragraph: the visual system linking every image — palette, "
                        "mood, product rendering, lighting."
                    ),
                },
                "slots": {
                    "type": "array",
                    "description": "One entry per requested (type, slot).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "description": "Image attribute type, e.g. HERO, INFOGRAPHIC.",
                            },
                            "slot": {
                                "type": "integer",
                                "description": (
                                    "1-based index that restarts at 1 within EACH type "
                                    "(not a running count across the whole gallery)."
                                ),
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


# --- Amazon text-attribute limits (single source of truth) -------------------
#
# TEXT_LIMITS drives all three layers so a number is never written twice:
# schema hints in ``text_attributes_tool`` (best-effort — providers do not
# reliably enforce maxLength/maxItems on tool arguments), the limit sentence in
# generation prompts, and the hard post-generation check in
# ``validate_text_value``. ``max_bytes`` exists because Amazon's backend search
# terms cap is 249 UTF-8 BYTES, which JSON Schema cannot express at all —
# that limit is only ever enforceable in code.


@dataclass(frozen=True, slots=True)
class TextLimit:
    max_chars: int | None = None
    min_chars: int | None = None
    max_bytes: int | None = None
    min_bytes: int | None = None
    item_count: int | None = None
    per_item_max_chars: int | None = None
    per_item_min_chars: int | None = None


# Amazon marketplace limits (title policy effective 2026-07-27). Maximums are
# Amazon's hard caps; minimums are ours — copy should fill the available space,
# so finishing far under the cap fails validation and triggers a repair retry.
TEXT_LIMITS: dict[AttributeName, TextLimit] = {
    AttributeName.TITLE: TextLimit(max_chars=75, min_chars=60),
    AttributeName.ITEM_HIGHLIGHTS: TextLimit(max_chars=125, min_chars=100),
    AttributeName.BULLET_POINTS: TextLimit(
        item_count=5, per_item_max_chars=200, per_item_min_chars=180
    ),
    AttributeName.KEY_FEATURES: TextLimit(
        item_count=5, per_item_max_chars=100, per_item_min_chars=80
    ),
    AttributeName.BACKEND_KEYWORDS: TextLimit(max_bytes=249, min_bytes=200),
}

# Attributes whose value is a list of strings (schema + persistence + validation).
LIST_TEXT_ATTRIBUTES = frozenset({AttributeName.BULLET_POINTS, AttributeName.KEY_FEATURES})


def limit_sentence(name: AttributeName) -> str | None:
    """One human-readable sentence stating the hard limits for ``name`` (for prompts)."""
    limit = TEXT_LIMITS.get(name)
    if limit is None:
        return None
    parts: list[str] = []
    if limit.max_chars is not None:
        if limit.min_chars is not None:
            parts.append(
                f"between {limit.min_chars} and {limit.max_chars} characters "
                "including spaces"
            )
        else:
            parts.append(f"at most {limit.max_chars} characters including spaces")
    if limit.max_bytes is not None:
        if limit.min_bytes is not None:
            parts.append(
                f"between {limit.min_bytes} and {limit.max_bytes} bytes when UTF-8 encoded"
            )
        else:
            parts.append(f"at most {limit.max_bytes} bytes when UTF-8 encoded")
    if limit.item_count is not None:
        parts.append(f"exactly {limit.item_count} items")
    if limit.per_item_max_chars is not None:
        if limit.per_item_min_chars is not None:
            parts.append(
                f"each item between {limit.per_item_min_chars} and "
                f"{limit.per_item_max_chars} characters"
            )
        else:
            parts.append(f"each item at most {limit.per_item_max_chars} characters")
    sentence = f"HARD LIMIT for {name.value}: " + ", ".join(parts) + "."
    has_minimum = (
        limit.min_chars is not None
        or limit.min_bytes is not None
        or limit.per_item_min_chars is not None
    )
    if has_minimum:
        sentence += (
            " Fill the available space — landing just under the maximum is ideal; "
            "finishing below the minimum is a failure."
        )
    return sentence


@dataclass(frozen=True, slots=True)
class Violation:
    """One failed limit check. Maximums are Amazon hard caps (never persist over
    them); minimums are our quality floors (retry, then accept with a warning)."""

    message: str
    is_minimum: bool = False


def violation_messages(violations: list["Violation"]) -> str:
    return "; ".join(violation.message for violation in violations)


def validate_text_value(name: AttributeName, value: Any) -> list[Violation]:
    """Violations for ``value`` against TEXT_LIMITS; empty list = passes.

    The authoritative enforcement layer — schema hints are advisory only.
    Checks the structured value (real list for list attributes), so item counts
    and per-item lengths are validated before any serialization.
    """
    limit = TEXT_LIMITS.get(name)
    if limit is None:
        return []

    violations: list[Violation] = []
    if name in LIST_TEXT_ATTRIBUTES:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return [Violation(f"{name.value} must be a list of strings")]
        if limit.item_count is not None and len(value) != limit.item_count:
            violations.append(
                Violation(f"{name.value} has {len(value)} items, expected {limit.item_count}")
            )
        for index, item in enumerate(value, start=1):
            if limit.per_item_max_chars is not None and len(item) > limit.per_item_max_chars:
                violations.append(
                    Violation(
                        f"{name.value} item {index} is {len(item)} characters, "
                        f"maximum {limit.per_item_max_chars}"
                    )
                )
            if limit.per_item_min_chars is not None and len(item) < limit.per_item_min_chars:
                violations.append(
                    Violation(
                        f"{name.value} item {index} is {len(item)} characters, "
                        f"minimum {limit.per_item_min_chars} — expand it to fill the space",
                        is_minimum=True,
                    )
                )
        return violations

    if not isinstance(value, str):
        return [Violation(f"{name.value} must be a string")]
    if limit.max_chars is not None and len(value) > limit.max_chars:
        violations.append(
            Violation(f"{name.value} is {len(value)} characters, maximum {limit.max_chars}")
        )
    if limit.min_chars is not None and len(value) < limit.min_chars:
        violations.append(
            Violation(
                f"{name.value} is {len(value)} characters, minimum {limit.min_chars} "
                "— expand it to fill the space",
                is_minimum=True,
            )
        )
    if limit.max_bytes is not None or limit.min_bytes is not None:
        size = len(value.encode("utf-8"))
        if limit.max_bytes is not None and size > limit.max_bytes:
            violations.append(
                Violation(f"{name.value} is {size} bytes, maximum {limit.max_bytes}")
            )
        if limit.min_bytes is not None and size < limit.min_bytes:
            violations.append(
                Violation(
                    f"{name.value} is {size} bytes, minimum {limit.min_bytes} "
                    "— add more relevant search terms",
                    is_minimum=True,
                )
            )
    return violations


def _text_property_schema(name: AttributeName) -> dict[str, Any]:
    """JSON-schema property for one text attribute, with best-effort limit hints."""
    limit = TEXT_LIMITS.get(name)
    if name in LIST_TEXT_ATTRIBUTES:
        items: dict[str, Any] = {"type": "string"}
        schema: dict[str, Any] = {
            "type": "array",
            "items": items,
            "description": f"{name.value} as an array of strings.",
        }
        if limit is not None:
            if limit.item_count is not None:
                schema["minItems"] = limit.item_count
                schema["maxItems"] = limit.item_count
            if limit.per_item_max_chars is not None:
                items["maxLength"] = limit.per_item_max_chars
            if limit.per_item_min_chars is not None:
                items["minLength"] = limit.per_item_min_chars
        return schema

    schema = {"type": "string", "description": f"Final copy for {name.value}."}
    if limit is not None:
        if limit.max_chars is not None:
            schema["maxLength"] = limit.max_chars
        if limit.min_chars is not None:
            schema["minLength"] = limit.min_chars
    return schema


def text_attributes_tool(names: list[AttributeName]) -> dict[str, Any]:
    """Tool schema whose arguments are exactly the requested text attributes."""
    properties: dict[str, Any] = {
        name.value: _text_property_schema(name) for name in names
    }
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
