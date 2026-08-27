"""OpenRouter tool schemas for inbound QC extract and judge."""

from __future__ import annotations

import copy
from typing import Any

from pipelines.inbound_qc.category import CATEGORY_BEDSHEET
from pipelines.inbound_qc.types import Checklist

INBOUND_QC_EXTRACT_TOOL_NAME = "submit_inbound_qc_extract"
INBOUND_QC_JUDGE_TOOL_NAME = "submit_inbound_qc_judge"

_DEFAULT_FIELDS = ("color", "pattern", "size", "item_count", "material")

INBOUND_QC_EXTRACT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": INBOUND_QC_EXTRACT_TOOL_NAME,
        "description": (
            "Describe what is visible on the product photos. "
            "Do not compare to catalog text. Do not OCR on-image text. "
            "Shopper-facing visual facts only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "enum": list(_DEFAULT_FIELDS),
                            },
                            "observed": {"type": "string"},
                            "visibility": {
                                "type": "string",
                                "enum": ["clear", "inferred", "not_visible"],
                            },
                            "confidence": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 100,
                            },
                            "evidence": {
                                "type": "string",
                                "enum": ["on_product", "room_context", "none"],
                            },
                            "images": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "name",
                            "observed",
                            "visibility",
                            "confidence",
                            "evidence",
                            "images",
                        ],
                        "additionalProperties": False,
                    },
                },
                "images_agree": {
                    "type": "boolean",
                    "description": "False when photos look like different product variants.",
                },
                "item_counts": {
                    "type": "object",
                    "properties": {
                        "total_visible": {
                            "type": "integer",
                            "minimum": 0,
                            "description": (
                                "Sellable pieces of this product in the photos, not props."
                            ),
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["fields", "images_agree"],
            "additionalProperties": False,
        },
    },
}

INBOUND_QC_JUDGE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": INBOUND_QC_JUDGE_TOOL_NAME,
        "description": (
            "Score catalog vs other-text pairs. Short observations and analysis only. "
            "Omit TBD, OCR, synonyms, and low-severity disagreements."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "conflicts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "pair_id": {"type": "string"},
                            "severity": {
                                "type": "string",
                                "enum": ["low", "medium", "high"],
                                "description": "low = ignore. medium/high = show the reviewer.",
                            },
                            "observation_1": {
                                "type": "string",
                                "description": "Where + what for side 1 (catalog Color: Yellow).",
                            },
                            "observation_2": {
                                "type": "string",
                                "description": "Where + what for side 2 (photo: green print).",
                            },
                            "analysis": {
                                "type": "string",
                                "description": "One short sentence. No extra context.",
                            },
                            "certainty": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 100,
                                "description": (
                                    "How sure this is a real contradiction, not a synonym."
                                ),
                            },
                            "similarity": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 100,
                                "description": (
                                    "How close the two values are. High = near-match "
                                    "(navy/blue). Low = clearly different (white/green)."
                                ),
                            },
                        },
                        "required": [
                            "pair_id",
                            "severity",
                            "observation_1",
                            "observation_2",
                            "analysis",
                            "certainty",
                            "similarity",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["conflicts"],
            "additionalProperties": False,
        },
    },
}


def extract_tool(checklist: Checklist) -> dict[str, Any]:
    """Tool schema limited to the fact types this batch's CSV headers can compare."""
    names = [name if name != "bed_size" else "size" for name in checklist.visual]
    if checklist.category == CATEGORY_BEDSHEET and "product_type" not in names:
        names = ["product_type", *names]
    if not names:
        names = list(_DEFAULT_FIELDS)
    tool = copy.deepcopy(INBOUND_QC_EXTRACT_TOOL)
    params = tool["function"]["parameters"]
    params["properties"]["fields"]["items"]["properties"]["name"]["enum"] = names
    if "item_count" not in names:
        params["properties"].pop("item_counts", None)
    return tool
