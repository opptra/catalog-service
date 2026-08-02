"""Generic helpers for working with LLM responses."""

import json
from typing import Any

from core.exceptions import OpenRouterError


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    # Drop the opening fence line (``` or ```json) and the trailing fence.
    body = stripped.split("\n", 1)[1] if "\n" in stripped else ""
    if body.rstrip().endswith("```"):
        body = body.rstrip()[: -len("```")]
    return body.strip()


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from an LLM response, tolerating ```json code fences."""
    try:
        parsed = json.loads(_strip_code_fence(text))
    except json.JSONDecodeError as exc:
        raise OpenRouterError("Model did not return valid JSON") from exc
    if not isinstance(parsed, dict):
        raise OpenRouterError("Model JSON was not an object")
    return parsed
