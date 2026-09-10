"""Fill-time ENUM selection via OpenRouter (constrained tool call)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from core.clients.openrouter import OpenRouterClient
from core.config import settings
from core.exceptions import OpenRouterError
from entities.catalog.attribute_enums import ListingFillGapReason

logger = logging.getLogger(__name__)

ENUM_PICKS_TOOL_NAME = "submit_listing_enum_picks"
_ENUM_MAX_TOKENS = 4096
_NO_VALID_VALUE_ACTIONS = frozenset(
    {
        "no_valid_value",
        ListingFillGapReason.ENUM_NO_VALID_VALUE.value.casefold(),
    }
)

_SYSTEM = (
    "You decide listing dropdown values from product evidence only. "
    "Ground truth is product_attributes and product images — nothing else. "
    "Never pick a 'closest' value, never invent, never use list defaults. "
    "For every column return exactly one action: "
    "fill (allowed list value the evidence supports), "
    "skip (the attribute does not apply to this product — e.g. League Name "
    "when the product has no league), or "
    "no_valid_value (the product clearly has this attribute, but none of the "
    "allowed values match that evidence). "
    "Do not use skip when evidence exists but is not on the list. "
    "Do not use no_valid_value when the attribute is simply absent."
)


@dataclass(frozen=True, slots=True)
class EnumPickResult:
    """Fill-time ENUM decisions. ``skip`` and omitted columns are not listed."""

    fills: dict[int, str] = field(default_factory=dict)
    no_valid_value: frozenset[int] = field(default_factory=frozenset)


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
    """Forced tool: every pending column gets fill, skip, or no_valid_value."""
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
                    "enum": ["fill", "skip", "no_valid_value"],
                    "description": (
                        f"For '{label}': fill when evidence matches one allowed "
                        "value; skip when the attribute does not apply; "
                        "no_valid_value when evidence exists but none of the "
                        "allowed values match."
                    ),
                },
                "value": {
                    "type": "string",
                    "enum": valid,
                    "description": (
                        f"Required when action=fill. Must be one of the allowed values "
                        f"for '{label}'. Omit when action=skip or no_valid_value."
                    ),
                },
            },
            "description": (
                f"Decision for column {col} ({label}). "
                "skip = not applicable. no_valid_value = evidence present, list misses it."
            ),
        }
    return {
        "type": "function",
        "function": {
            "name": ENUM_PICKS_TOOL_NAME,
            "description": (
                "Submit an explicit decision for every unresolved ENUM column. "
                "action=fill requires a value from that column's allowed list. "
                "action=skip leaves the cell blank (attribute does not apply). "
                "action=no_valid_value means the product has this attribute but "
                "no allowed value matches — do not guess a closest option."
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
) -> EnumPickResult:
    """Return fill and no_valid_value decisions for unresolved ENUM columns.

    Batches pending ENUM fields in one call with PIM attributes and product images.
    ``skip`` and rejected/undecided columns are omitted — they are not treated as
    ``no_valid_value``.
    """
    if not enums_to_pick:
        return EnumPickResult()

    payload = {
        "sku_id": sku_id,
        "product_attributes": product_attributes,
        "already_filled": already_filled,
        "enums_to_pick": [
            {
                "column_index": str(item["column_index"]),
                "label": item.get("label"),
                "valid_values": item["valid_values"],
                "instruction": (
                    "Return fill + value from valid_values when evidence matches; "
                    "skip when the attribute does not apply; no_valid_value when "
                    "evidence exists but no valid_values entry matches."
                ),
            }
            for item in enums_to_pick
        ],
        "rules": [
            "No evidence / attribute does not apply → action=skip (leave blank).",
            "Evidence present but none of valid_values match → action=no_valid_value.",
            "Do not treat skip as no_valid_value, and do not guess a closest value.",
            "Never invent or choose a list default.",
        ],
    }
    prompt = (
        "For each enums_to_pick column, decide fill, skip, or no_valid_value using "
        "product_attributes and product images only. Call the tool with decisions "
        "for EVERY column_index.\n\n"
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
        return EnumPickResult()

    return _parse_enum_decisions(args, enums_to_pick=enums_to_pick, sku_id=sku_id)


def _parse_enum_decisions(
    args: dict[str, Any] | Any,
    *,
    enums_to_pick: list[dict[str, Any]],
    sku_id: str,
) -> EnumPickResult:
    """Interpret tool output. Blank or skip is not ENUM_NO_VALID_VALUE."""
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
        return EnumPickResult()

    allowed_by_col = {
        int(item["column_index"]): set(item["valid_values"]) for item in enums_to_pick
    }
    label_by_col = {
        int(item["column_index"]): str(item.get("label") or item["column_index"])
        for item in enums_to_pick
    }
    fills: dict[int, str] = {}
    no_valid_value: set[int] = set()
    skipped_cols: set[int] = set()
    skipped_log: list[str] = []
    no_match_log: list[str] = []
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
        if action == "no_valid_value":
            no_valid_value.add(col)
            no_match_log.append(f"{col}:{label}")
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
        fills[col] = text

    requested = {int(item["column_index"]) for item in enums_to_pick}
    undecided = sorted(requested - set(fills) - skipped_cols - no_valid_value)
    logger.info(
        "ENUM pick done sku_id=%s picked=%s skipped=%s no_valid_value=%s "
        "undecided_cols=%s rejected=%s",
        sku_id,
        {str(k): v for k, v in sorted(fills.items())},
        skipped_log,
        no_match_log,
        undecided,
        rejected,
    )
    return EnumPickResult(fills=fills, no_valid_value=frozenset(no_valid_value))


def _normalize_decision(decision: Any) -> tuple[str | None, str | None]:
    """Accept structured {action,value} or legacy bare string value (=fill)."""
    if isinstance(decision, str):
        text = decision.strip()
        if not text or _is_blank_or_na(text) or text.casefold() == "skip":
            return "skip", None
        if text.casefold() in _NO_VALID_VALUE_ACTIONS:
            return "no_valid_value", None
        return "fill", text
    if not isinstance(decision, dict):
        return None, None
    action_raw = decision.get("action")
    action = str(action_raw).strip().casefold() if action_raw is not None else None
    value = decision.get("value")
    value_str = value.strip() if isinstance(value, str) else None
    if action in {"skip", "omit", "blank"}:
        return "skip", None
    if action in _NO_VALID_VALUE_ACTIONS:
        return "no_valid_value", None
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
