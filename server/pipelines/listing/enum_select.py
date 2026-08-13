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
_ENUM_MAX_TOKENS = 4096

_SYSTEM = (
    "You decide Amazon listing dropdown values from product evidence only. "
    "Ground truth is product_attributes and product images — nothing else. "
    "Rule of thumb: if the product does not clearly state or show the attribute, "
    "you MUST skip that field. Leaving it blank is correct; guessing is wrong. "
    "Examples that must be skipped when unsupported: League Name, Team Name, "
    "sports affiliations, or any marketplace option not mentioned for this SKU. "
    "Never pick a 'closest' value, never invent, never use list defaults. "
    "For every column in the tool schema you must return an explicit decision: "
    "action=fill with a value from that column's allowed list, or action=skip."
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
    """Forced tool: every pending column gets an explicit fill|skip decision."""
    properties: dict[str, Any] = {}
    required_cols: list[str] = []
    for item in enums_to_pick:
        col = str(item["column_index"])
        required_cols.append(col)
        valid = list(item["valid_values"])
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
                        f"For '{label}': use fill only when product evidence clearly "
                        "supports one allowed value; otherwise skip."
                    ),
                },
                "value": {
                    "type": "string",
                    "enum": valid,
                    "description": (
                        f"Required when action=fill. Must be one of the allowed values "
                        f"for '{label}'. Omit when action=skip."
                    ),
                },
            },
            "description": (
                f"Decision for column {col} ({label}). "
                "Prefer skip whenever evidence is missing, empty, unrelated, or weak."
            ),
        }
    return {
        "type": "function",
        "function": {
            "name": ENUM_PICKS_TOOL_NAME,
            "description": (
                "Submit an explicit fill-or-skip decision for every unresolved ENUM "
                "column. action=skip leaves the Excel cell blank (correct when the "
                "product has no supporting info). action=fill requires value from "
                "that column's enum. Do not invent or approximate."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["decisions"],
                "properties": {
                    "decisions": {
                        "type": "object",
                        "description": (
                            "Map of column_index → decision. Every listed column_index "
                            "key is required."
                        ),
                        "properties": properties,
                        "required": required_cols,
                        "additionalProperties": False,
                    }
                },
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
    product_image_urls: list[str] | None = None,
    product_image_url: str | None = None,
) -> dict[int, str]:
    """Return column_index → chosen valid value for unresolved ENUM columns.

    Batches pending ENUM fields in one call with PIM attributes and product images.
    Columns the model marks action=skip (or rejects) are omitted from the result.
    """
    if not enums_to_pick:
        return {}

    payload = {
        "sku_id": sku_id,
        "product_attributes": product_attributes,
        "already_filled": already_filled,
        "enums_to_pick": [
            {
                "column_index": str(item["column_index"]),
                "label": item.get("label"),
                "machine_key": item.get("machine_key"),
                "valid_values": item["valid_values"],
                "instruction": (
                    "Return decisions[column_index]={action:'fill', value:<one of "
                    "valid_values>} only if evidence clearly supports it; otherwise "
                    "{action:'skip'} with no value."
                ),
            }
            for item in enums_to_pick
        ],
        "rules": [
            "No evidence → action=skip (leave blank).",
            "Empty / missing / unrelated PIM attribute → action=skip.",
            "Do not pick sports leagues, teams, or other options just because they "
            "appear in valid_values.",
            "Never guess or choose a default.",
        ],
    }
    prompt = (
        "For each enums_to_pick column, decide fill or skip using product_attributes "
        "and product images only. Call the tool with decisions for EVERY column_index. "
        "If information is not present, action must be skip.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    urls = [url for url in (product_image_urls or []) if url]
    if not urls and product_image_url:
        urls = [product_image_url]

    model = settings.openrouter_text_model
    field_summary = _enum_batch_summary(enums_to_pick)
    logger.info(
        "ENUM pick start sku_id=%s model=%s fields=%s attr_keys=%s images=%s "
        "prompt_chars=%s max_tokens=%s",
        sku_id,
        model,
        field_summary,
        len(product_attributes),
        len(urls),
        len(prompt),
        _ENUM_MAX_TOKENS,
    )
    try:
        args = client.call_tool(
            prompt,
            model=model,
            tool=pick_enums_tool(enums_to_pick),
            image_urls=urls or None,
            system=_SYSTEM,
            temperature=0.0,
            max_tokens=_ENUM_MAX_TOKENS,
        )
    except (OpenRouterError, ValueError) as exc:
        logger.warning(
            "ENUM pick failed sku_id=%s model=%s fields=%s attr_keys=%s images=%s "
            "prompt_chars=%s error=%s",
            sku_id,
            model,
            field_summary,
            len(product_attributes),
            len(urls),
            len(prompt),
            exc,
        )
        return {}

    return _parse_enum_decisions(args, enums_to_pick=enums_to_pick, sku_id=sku_id)


def _parse_enum_decisions(
    args: dict[str, Any] | Any,
    *,
    enums_to_pick: list[dict[str, Any]],
    sku_id: str,
) -> dict[int, str]:
    """Interpret tool output; only action=fill with a valid value is kept."""
    field_summary = _enum_batch_summary(enums_to_pick)
    raw = args.get("decisions") if isinstance(args, dict) else None
    # Backward-compatible: old schema used flat picks map of strings.
    if raw is None and isinstance(args, dict) and isinstance(args.get("picks"), dict):
        raw = args["picks"]
    if not isinstance(raw, dict):
        logger.warning(
            "ENUM pick missing decisions object sku_id=%s fields=%s args_keys=%s",
            sku_id,
            field_summary,
            sorted(args.keys()) if isinstance(args, dict) else type(args).__name__,
        )
        return {}

    allowed_by_col = {
        int(item["column_index"]): set(item["valid_values"]) for item in enums_to_pick
    }
    label_by_col = {
        int(item["column_index"]): str(item.get("label") or item["column_index"])
        for item in enums_to_pick
    }
    result: dict[int, str] = {}
    skipped_cols: set[int] = set()
    skipped_log: list[str] = []
    rejected: list[str] = []

    for key, decision in raw.items():
        try:
            col = int(key)
        except (TypeError, ValueError):
            rejected.append(f"{key!r}:bad_column_key")
            continue
        label = label_by_col.get(col, str(col))
        allowed = allowed_by_col.get(col)
        if allowed is None:
            rejected.append(f"{col}:unexpected_column")
            continue

        action, value = _normalize_decision(decision)
        if action == "skip":
            skipped_cols.add(col)
            skipped_log.append(f"{col}:{label}")
            continue
        if action != "fill":
            rejected.append(f"{col}:{label}:bad_action={action!r}")
            continue
        if value is None or _is_blank_or_na(value):
            rejected.append(f"{col}:{label}:fill_without_value")
            continue
        text = value.strip()
        if text not in allowed:
            rejected.append(f"{col}:{label}:not_in_valid_values value={text!r}")
            continue
        result[col] = text

    requested = {int(item["column_index"]) for item in enums_to_pick}
    undecided = sorted(requested - set(result) - skipped_cols)
    logger.info(
        "ENUM pick done sku_id=%s picked=%s skipped=%s undecided_cols=%s rejected=%s",
        sku_id,
        {str(k): v for k, v in sorted(result.items())},
        skipped_log,
        undecided,
        rejected,
    )
    return result


def _normalize_decision(decision: Any) -> tuple[str | None, str | None]:
    """Accept structured {action,value} or legacy bare string value (=fill)."""
    if isinstance(decision, str):
        text = decision.strip()
        if not text or _is_blank_or_na(text) or text.casefold() == "skip":
            return "skip", None
        return "fill", text
    if not isinstance(decision, dict):
        return None, None
    action_raw = decision.get("action")
    action = str(action_raw).strip().casefold() if action_raw is not None else None
    value = decision.get("value")
    value_str = value.strip() if isinstance(value, str) else None
    if action in {"skip", "omit", "blank"}:
        return "skip", None
    if action in {"fill", "set", "use"}:
        return "fill", value_str
    # If model only sent value without action, treat as fill attempt.
    if value_str and action is None:
        return "fill", value_str
    return action, value_str


def _enum_batch_summary(enums_to_pick: list[dict[str, Any]]) -> str:
    """Human-readable list of columns in this ENUM OpenRouter batch."""
    parts: list[str] = []
    for item in enums_to_pick:
        col = item.get("column_index")
        label = item.get("label") or "?"
        n_valid = len(item.get("valid_values") or [])
        parts.append(f"{col}:{label}(valid={n_valid})")
    return "[" + ", ".join(parts) + "]"


def _is_blank_or_na(text: str) -> bool:
    needle = text.casefold()
    return needle in {"", "n/a", "na", "none", "null", "not applicable", "unknown"}
