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


# --- Amazon text-attribute limits (single source of truth for the JSON tool) --
#
# TEXT_LIMITS exists only to build ``text_attributes_tool`` schema constraints
# (minLength/maxLength/minItems/maxItems + property descriptions). Do not
# restate these numbers in prompts or re-check them in Python — the JSON tool
# is the criteria definition the model must satisfy.
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


# Amazon marketplace limits (title policy effective 2026-07-27). Maximums are
# Amazon's hard caps; minimums are ours — copy should fill the available space.
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


def _limit_description(limit: TextLimit) -> str:
    """Human-readable limit summary embedded in the tool property description."""
    parts: list[str] = []
    if limit.max_chars is not None:
        if limit.min_chars is not None:
            parts.append(
                f"between {limit.min_chars} and {limit.max_chars} characters including spaces"
            )
        else:
            parts.append(f"at most {limit.max_chars} characters including spaces")
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
        if limit.per_item_min_chars is not None:
            parts.append(
                f"each item between {limit.per_item_min_chars} and "
                f"{limit.per_item_max_chars} characters"
            )
        else:
            parts.append(f"each item at most {limit.per_item_max_chars} characters")
    if not parts:
        return ""
    sentence = "HARD LIMIT: " + ", ".join(parts) + "."
    has_minimum = (
        limit.min_chars is not None
        or limit.per_item_min_chars is not None
        or (limit.min_items is not None and limit.item_count is None)
    )
    if has_minimum:
        sentence += (
            " Fill the available space — landing just under the maximum is ideal; "
            "finishing below the minimum is a failure."
        )
    return sentence


def _text_property_schema(name: AttributeName) -> dict[str, Any]:
    """JSON-schema property for one text attribute, with limit criteria on the tool."""
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
            if limit.per_item_max_chars is not None:
                items["maxLength"] = limit.per_item_max_chars
            if limit.per_item_min_chars is not None:
                items["minLength"] = limit.per_item_min_chars
        return schema

    description = f"Final copy for {name.value}."
    schema = {"type": "string", "description": description}
    if limit is not None:
        limit_note = _limit_description(limit)
        if limit_note:
            schema["description"] = f"{description} {limit_note}"
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
