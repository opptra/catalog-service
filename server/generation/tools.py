"""OpenRouter tool schemas for structured generation outputs.

JSON results are collected via forced tool calls (not free-form JSON in the
assistant message). The tool is never executed — its ``arguments`` *are* the
structured payload we want.
"""

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


def text_attributes_tool(names: list[AttributeName]) -> dict[str, Any]:
    """Tool schema whose arguments are exactly the requested text attributes."""
    properties: dict[str, Any] = {}
    for name in names:
        if name == AttributeName.BULLET_POINTS:
            properties[name.value] = {
                "type": "array",
                "items": {"type": "string"},
                "description": "Marketplace bullet points as an array of strings.",
            }
        else:
            properties[name.value] = {
                "type": "string",
                "description": f"Final copy for {name.value}.",
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
