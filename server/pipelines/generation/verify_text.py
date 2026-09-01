"""Post-generation verification for TEXT attributes — claims vs fact sheet."""

from __future__ import annotations

import json
from typing import Any

from core.clients.openrouter import OpenRouterClient
from core.config import settings
from entities.catalog.attribute_enums import AttributeName
from pipelines.generation import tools
from pipelines.generation.verify import (
    _REASONING_MAX_CHARS,
    _SLOT_FIELD_MAX_CHARS,
    _VERIFY_MAX_TOKENS,
    STATUS_OK,
    VerificationResult,
    _clamp_confidence,
    _optional_clip,
    _parse_mismatches,
    _product_facts,
)


def format_text_value_for_verification(name: AttributeName, raw: Any) -> str:
    """Human-readable copy block sent to the text verifier."""
    if raw is None:
        return ""
    list_like = name in tools.LIST_TEXT_ATTRIBUTES or name == AttributeName.BACKEND_KEYWORDS
    if list_like and isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                raw = parsed
        except ValueError:
            pass
    if list_like:
        if isinstance(raw, list):
            if name == AttributeName.BACKEND_KEYWORDS:
                return " ".join(str(item).strip() for item in raw if item)
            return "\n".join(f"- {item}" for item in raw if item)
        return str(raw).strip()
    return str(raw).strip()


def verify_text_attribute(
    client: OpenRouterClient,
    *,
    attribute_name: str,
    generated_text: str,
    product: dict[str, Any],
    attempt: int = 1,
    session_id: str | None = None,
) -> VerificationResult:
    """Score listing copy on claims vs PRODUCT DATA (fact sheet). Uses verify model (gpt-4o)."""
    model = settings.openrouter_verify_model
    facts = _product_facts(product)
    prefix = (
        "=== PRODUCT DATA (authoritative — every key AND every value is a fact) ===\n"
        f"{json.dumps(facts, ensure_ascii=False, indent=2)}"
    )
    suffix = _text_verify_suffix(generated_text=generated_text)
    parsed = client.call_tool(
        suffix,
        model=model,
        tool=tools.TEXT_VERIFICATION_TOOL,
        cache_prefix=prefix,
        max_tokens=_VERIFY_MAX_TOKENS,
        session_id=session_id,
    )
    return _parse_text_tool(
        parsed,
        model=model,
        attempt=attempt,
        attribute_name=attribute_name,
    )


def _text_verify_suffix(*, generated_text: str) -> str:
    return (
        "You verify generated listing copy before it ships.\n\n"
        "GENERATED COPY:\n"
        f"{generated_text.strip() or '(empty)'}\n\n"
        "Direction is ONE-WAY: read ONLY what this copy states. For each factual assertion "
        "in it, check whether PRODUCT DATA above supports it. PRODUCT DATA is authoritative; "
        "this copy is what you audit.\n\n"
        "Omission is always allowed. PRODUCT DATA may contain many facts this copy does not "
        "mention. If the copy simply leaves them out, that is NOT an error, does NOT lower "
        "the score, and must NOT appear in mismatches or reasoning as a problem.\n\n"
        "Do NOT compare the copy to a full PRODUCT DATA value and treat missing words as a "
        "mismatch. Shorter or partial copy is fine when every stated fact is supported.\n\n"
        "Set claims to an integer PERCENTAGE from 0 to 100 (not a count of assertions). "
        "It is the overall support score for what the copy states:\n"
        "- 95–100: every stated fact is supported; mismatches must be [].\n"
        "- 80–94: minor uncertainty but no clear contradiction or invention.\n"
        "- Below 80: only when the copy states facts that contradict or invent.\n"
        "If reasoning concludes all stated facts are supported, claims must be at least 95.\n\n"
        "Score on what the copy ASSERTS:\n"
        "- Contradiction: the copy states a fact that conflicts with PRODUCT DATA. The "
        "relevant field wins. Synonyms match.\n"
        "- Invented: the copy states a fact (or clear synonym) that appears in NO key and NO "
        "value anywhere in PRODUCT DATA.\n\n"
        "mismatch kind: contradiction | invented only.\n"
        "Emit a mismatch only for something the copy actually says. Never for something it "
        "omitted. For contradiction, set source_field and catalog from PRODUCT DATA. "
        "For invented, observed only.\n\n"
        "In reasoning, note briefly whether stated claims are supported. Do not criticise "
        "omitted facts.\n\n"
        "Call the submit_text_verification tool. Do not write JSON in the message body."
    )


def _parse_text_tool(
    parsed: dict[str, Any],
    *,
    model: str,
    attempt: int,
    attribute_name: str,
) -> VerificationResult:
    if not isinstance(parsed, dict):
        raise ValueError("text verification tool returned a non-object")
    claims = _clamp_confidence(parsed.get("claims"))
    reasoning = _optional_clip(parsed.get("reasoning"), _REASONING_MAX_CHARS) or ""
    mismatches = _parse_mismatches(parsed.get("mismatches"))
    return VerificationResult(
        status=STATUS_OK,
        model=model,
        attempt=attempt,
        confidence=claims,
        identity=None,
        claims=claims,
        quality=None,
        reasoning=reasoning,
        observed_text=(),
        mismatches=tuple(mismatches),
        attribute_name=_optional_clip(attribute_name, _SLOT_FIELD_MAX_CHARS),
    )
