"""Fill-time free-text generation via OpenRouter (batched tool call)."""

from __future__ import annotations

import json
import logging
from typing import Any

from core.clients.openrouter import OpenRouterClient
from core.config import settings
from core.exceptions import OpenRouterError

logger = logging.getLogger(__name__)

AI_TEXT_TOOL_NAME = "submit_listing_ai_text"

_SYSTEM = (
    "You write short Amazon listing field values from evidence only. "
    "Ground truth is product_attributes and product images. "
    "Rule of thumb: if the product does not clearly support a field, skip it — "
    "blank is correct, guessing is wrong. "
    "For every column in the tool schema return an explicit decision: "
    "action=fill with a short value, or action=skip."
)


def generate_texts_tool(fields: list[dict[str, Any]]) -> dict[str, Any]:
    """Forced tool: every pending AI_TEXT column gets fill|skip."""
    properties: dict[str, Any] = {}
    required_cols: list[str] = []
    for item in fields:
        col = str(item["column_index"])
        required_cols.append(col)
        label = item.get("label") or col
        properties[col] = {
            "type": "object",
            "additionalProperties": False,
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["fill", "skip"],
                    "description": (
                        f"For '{label}': fill only with clear product evidence; otherwise skip."
                    ),
                },
                "value": {
                    "type": "string",
                    "description": (
                        f"Short marketplace text for '{label}'. "
                        "Required when action=fill; omit when action=skip."
                    ),
                },
            },
            "description": (f"Decision for column {col} ({label}). Prefer skip when unsure."),
        }
    return {
        "type": "function",
        "function": {
            "name": AI_TEXT_TOOL_NAME,
            "description": (
                "Submit fill-or-skip decisions for unresolved AI_TEXT listing columns. "
                "action=skip leaves the cell blank. action=fill requires value. "
                "Do not invent facts."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["decisions"],
                "properties": {
                    "decisions": {
                        "type": "object",
                        "properties": properties,
                        "required": required_cols,
                        "additionalProperties": False,
                    }
                },
            },
        },
    }


def generate_texts(
    client: OpenRouterClient,
    *,
    sku_id: str,
    product_attributes: dict[str, Any],
    already_filled: dict[str, str],
    fields: list[dict[str, Any]],
    product_image_urls: list[str] | None = None,
) -> dict[int, str]:
    """Return column_index → generated text for unresolved AI_TEXT columns.

    Batches every pending field in one call. Always includes PIM attributes and
    any available product image URLs for visual context.
    """
    if not fields:
        return {}

    payload = {
        "sku_id": sku_id,
        "product_attributes": product_attributes,
        "already_filled": already_filled,
        "fields_to_generate": [
            {
                "column_index": str(item["column_index"]),
                "label": item.get("label"),
                "instruction": (
                    "Return decisions[column_index]={action:'fill', value:'...'} only "
                    "if evidence clearly supports it; otherwise {action:'skip'}."
                ),
            }
            for item in fields
        ],
        "rules": [
            "No evidence → action=skip.",
            "Never invent dimensions, materials, or claims.",
        ],
    }
    prompt = (
        "For each fields_to_generate column, decide fill or skip from "
        "product_attributes and product images only. Call the tool with decisions "
        "for EVERY column_index. If information is not present, action must be skip.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    image_urls = [url for url in (product_image_urls or []) if url]
    try:
        args = client.call_tool(
            prompt,
            model=settings.openrouter_text_model,
            tool=generate_texts_tool(fields),
            image_urls=image_urls or None,
            system=_SYSTEM,
            temperature=0.2,
            max_tokens=2048,
        )
    except (OpenRouterError, ValueError) as exc:
        logger.warning("AI_TEXT generate failed for sku_id=%s: %s", sku_id, exc)
        return {}

    raw = args.get("decisions") if isinstance(args, dict) else None
    if raw is None and isinstance(args, dict) and isinstance(args.get("values"), dict):
        raw = args["values"]
    if not isinstance(raw, dict):
        return {}

    allowed = {int(item["column_index"]) for item in fields}
    result: dict[int, str] = {}
    skipped: list[str] = []
    for key, decision in raw.items():
        try:
            col = int(key)
        except (TypeError, ValueError):
            continue
        if col not in allowed:
            continue
        if isinstance(decision, str):
            text = decision.strip()
            if not text or _is_blank_or_na(text) or text.casefold() == "skip":
                skipped.append(str(col))
                continue
            result[col] = text
            continue
        if not isinstance(decision, dict):
            continue
        action = str(decision.get("action") or "").strip().casefold()
        value = decision.get("value")
        if action in {"skip", "omit", "blank"}:
            skipped.append(str(col))
            continue
        if action not in {"fill", "set", "use", ""}:
            continue
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text or _is_blank_or_na(text):
            continue
        result[col] = text

    logger.info(
        "AI_TEXT done sku_id=%s filled=%s skipped=%s",
        sku_id,
        {str(k): v for k, v in sorted(result.items())},
        skipped,
    )
    return result


def _is_blank_or_na(text: str) -> bool:
    needle = text.casefold()
    return needle in {"", "n/a", "na", "none", "null", "not applicable", "unknown"}
