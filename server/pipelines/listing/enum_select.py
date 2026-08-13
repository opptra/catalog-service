"""Fill-time ENUM selection via OpenRouter (constrained tool call)."""

from __future__ import annotations

import json
import logging
from typing import Any

from core.clients.openrouter import OpenRouterClient
from core.config import settings
from core.exceptions import OpenRouterError

logger = logging.getLogger(__name__)

ENUM_PICKS_TOOL_NAME = "submit_listing_enum_picks"

_SYSTEM = (
    "You pick Amazon listing dropdown values. "
    "For each field, choose exactly one value from that field's valid_values list, "
    "or omit the field if you cannot choose confidently. "
    "Never invent values outside the provided lists."
)


def match_exact(value: str | None, valid_values: list[str]) -> str | None:
    """Case-insensitive exact match against Amazon valid_values."""
    if value is None:
        return None
    needle = value.strip()
    if not needle:
        return None
    for candidate in valid_values:
        if candidate.casefold() == needle.casefold():
            return candidate
    return None


def pick_enums_tool(enums_to_pick: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a forced tool schema: picks map keyed by column_index string."""
    properties: dict[str, Any] = {}
    for item in enums_to_pick:
        col = str(item["column_index"])
        valid = list(item["valid_values"])
        properties[col] = {
            "type": "string",
            "enum": valid,
            "description": (f"{item.get('label') or col}: choose one of the allowed values."),
        }
    return {
        "type": "function",
        "function": {
            "name": ENUM_PICKS_TOOL_NAME,
            "description": (
                "Submit Amazon dropdown picks for the unresolved ENUM columns. "
                "Keys are column_index strings; values must be from that column's enum."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "picks": {
                        "type": "object",
                        "properties": properties,
                        "additionalProperties": False,
                    }
                },
                "required": ["picks"],
            },
        },
    }


def pick_enums(
    client: OpenRouterClient,
    *,
    sku_id: str,
    product_attributes: dict[str, Any],
    already_filled: dict[str, str],
    enums_to_pick: list[dict[str, Any]],
    product_image_url: str | None = None,
) -> dict[int, str]:
    """Return column_index → chosen valid value for unresolved ENUM columns.

    Minimal contract: product attributes, optional one image, already-filled cells,
    and only the pending ENUM fields with their valid_values.
    """
    if not enums_to_pick:
        return {}

    payload = {
        "sku_id": sku_id,
        "product_attributes": product_attributes,
        "already_filled": already_filled,
        "enums_to_pick": [
            {
                "column_index": item["column_index"],
                "label": item.get("label"),
                "machine_key": item.get("machine_key"),
                "valid_values": item["valid_values"],
            }
            for item in enums_to_pick
        ],
    }
    prompt = (
        "Pick legal Amazon dropdown values for this SKU.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    image_urls = [product_image_url] if product_image_url else None
    try:
        args = client.call_tool(
            prompt,
            model=settings.openrouter_text_model,
            tool=pick_enums_tool(enums_to_pick),
            image_urls=image_urls,
            system=_SYSTEM,
            temperature=0.0,
            max_tokens=2048,
        )
    except (OpenRouterError, ValueError) as exc:
        logger.warning("ENUM pick failed for sku_id=%s: %s", sku_id, exc)
        return {}

    raw_picks = args.get("picks") if isinstance(args, dict) else None
    if not isinstance(raw_picks, dict):
        return {}

    allowed_by_col = {
        int(item["column_index"]): set(item["valid_values"]) for item in enums_to_pick
    }
    result: dict[int, str] = {}
    for key, value in raw_picks.items():
        try:
            col = int(key)
        except (TypeError, ValueError):
            continue
        if not isinstance(value, str):
            continue
        allowed = allowed_by_col.get(col)
        if allowed is None or value not in allowed:
            continue
        result[col] = value
    return result
