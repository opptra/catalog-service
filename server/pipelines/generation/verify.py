"""Post-render product-data verification for IMAGE / A_PLUS slots.

The vision model reads the generated image only (no source photos) and compares
on-image claims to ``sku_master.attributes``. Omission is allowed; contradiction
and invented copy are not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from core.clients.openrouter import OpenRouterClient
from core.config import settings
from pipelines.generation import tools

# Change this constant to raise/lower the retry bar. Not an env var.
MIN_CONFIDENCE_PERCENT = 80

SCHEMA_VERSION = 1
STATUS_OK = "ok"
STATUS_ERROR = "error"
KIND_CONTRADICTION = "contradiction"
KIND_INVENTED = "invented"
_ALLOWED_KINDS = frozenset({KIND_CONTRADICTION, KIND_INVENTED})

_VERIFY_MAX_TOKENS = 800
_REASONING_MAX_CHARS = 500
_OBSERVED_MAX_ITEMS = 40
_OBSERVED_ITEM_MAX_CHARS = 120
_MISMATCH_MAX = 20
_MISMATCH_FIELD_MAX_CHARS = 120
_ERROR_MAX_CHARS = 200


@dataclass(frozen=True, slots=True)
class VerificationMismatch:
    kind: str
    source_field: str | None
    catalog: str | None
    observed: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source_field": self.source_field,
            "catalog": self.catalog,
            "observed": self.observed,
        }


@dataclass(frozen=True, slots=True)
class VerificationResult:
    status: str
    model: str
    attempt: int
    confidence: int | None = None
    reasoning: str | None = None
    observed_text: tuple[str, ...] = ()
    mismatches: tuple[VerificationMismatch, ...] = ()
    error: str | None = None

    def below_threshold(self) -> bool:
        return (
            self.status == STATUS_OK
            and self.confidence is not None
            and self.confidence < MIN_CONFIDENCE_PERCENT
        )

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "v": SCHEMA_VERSION,
            "status": self.status,
            "model": self.model,
            "attempt": self.attempt,
        }
        if self.status == STATUS_ERROR:
            payload["error"] = self.error or "verify_tool_call_failed"
            return payload
        payload["confidence"] = 0 if self.confidence is None else self.confidence
        payload["threshold"] = MIN_CONFIDENCE_PERCENT
        payload["reasoning"] = self.reasoning or ""
        payload["observed_text"] = list(self.observed_text)
        payload["mismatches"] = [item.to_json() for item in self.mismatches]
        return payload


def error_result(*, model: str, attempt: int, error: str) -> VerificationResult:
    """Persistable failure when the verifier itself did not complete."""
    return VerificationResult(
        status=STATUS_ERROR,
        model=model,
        attempt=attempt,
        error=_clip(error, _ERROR_MAX_CHARS) or "verify_tool_call_failed",
    )


def retry_addendum(result: VerificationResult) -> str:
    """Ephemeral instructions for a one-shot re-render. Not stored on ``prompt``."""
    lines = [
        "The previous render failed product-data verification. Fix ONLY the issues below. "
        "Do not invent new product facts. PRODUCT DATA remains the only source of truth.",
        "",
        "Mismatches:",
    ]
    if not result.mismatches:
        lines.append(
            f"- overall confidence {result.confidence}% was below {MIN_CONFIDENCE_PERCENT}%"
        )
    for item in result.mismatches:
        if item.kind == KIND_CONTRADICTION:
            lines.append(
                f'- contradiction: on-image "{item.observed}" vs catalog '
                f'{item.source_field}="{item.catalog}"'
            )
        else:
            lines.append(f'- invented: on-image "{item.observed}" is not in PRODUCT DATA')
    if result.reasoning:
        lines.append("")
        lines.append(f"Verifier note: {result.reasoning}")
    return "\n".join(lines)


def verify_image(
    client: OpenRouterClient,
    *,
    generated_image_url: str,
    product: dict[str, Any],
    attempt: int,
    session_id: str | None = None,
) -> VerificationResult:
    """OCR the generated image and score it against PRODUCT DATA only.

    ``generated_image_url`` is the only image attached — never source photos.
    """
    model = settings.openrouter_verify_model
    facts = _product_facts(product)
    prefix = (
        "=== PRODUCT DATA (authoritative — the ONLY source of product facts) ===\n"
        f"{json.dumps(facts, ensure_ascii=False, indent=2)}"
    )
    suffix = (
        "You verify ONE generated catalog image against PRODUCT DATA.\n"
        "The attached image is the generated slot — there are no source/reference photos.\n"
        "Read every shopper-facing word, badge, and label on the image.\n\n"
        "RULES:\n"
        "- PRODUCT DATA is truth. Synonyms that mean the same fact match "
        '(e.g. "King Size" vs "King").\n'
        "- Omission is allowed: a hero with little or no text can score high.\n"
        "- Contradiction (on-image text fights an attribute) is a miss.\n"
        "- Invented copy that is not in PRODUCT DATA is a miss.\n"
        "- SKU, ASIN, UPC, EAN, or GTIN printed on the artwork is invented.\n"
        "- Do not score visual likeness, color accuracy, or composition vs photos.\n"
        "- confidence is an integer 0–100 for how sure you are the on-image claims "
        "agree with PRODUCT DATA.\n\n"
        "Call the submit_image_verification tool. Do not write JSON in the message body."
    )
    parsed = client.call_tool(
        suffix,
        model=model,
        tool=tools.IMAGE_VERIFICATION_TOOL,
        image_urls=[generated_image_url],
        cache_prefix=prefix,
        max_tokens=_VERIFY_MAX_TOKENS,
        session_id=session_id,
    )
    return _parse_tool(parsed, model=model, attempt=attempt)


def _product_facts(product: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in product.items() if key != "source_assets"}


def _parse_tool(parsed: dict[str, Any], *, model: str, attempt: int) -> VerificationResult:
    if not isinstance(parsed, dict):
        raise ValueError("verification tool returned a non-object")
    confidence = _clamp_confidence(parsed.get("confidence"))
    reasoning = _clip(str(parsed.get("reasoning") or "").strip(), _REASONING_MAX_CHARS)
    observed = _parse_observed(parsed.get("observed_text"))
    mismatches = _parse_mismatches(parsed.get("mismatches"))
    return VerificationResult(
        status=STATUS_OK,
        model=model,
        attempt=attempt,
        confidence=confidence,
        reasoning=reasoning,
        observed_text=tuple(observed),
        mismatches=tuple(mismatches),
    )


def _clamp_confidence(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise ValueError("verification confidence missing or invalid")
    return max(0, min(100, int(round(float(raw)))))


def _parse_observed(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = _clip(str(item).strip(), _OBSERVED_ITEM_MAX_CHARS)
        if text:
            out.append(text)
        if len(out) >= _OBSERVED_MAX_ITEMS:
            break
    return out


def _parse_mismatches(raw: Any) -> list[VerificationMismatch]:
    if not isinstance(raw, list):
        return []
    out: list[VerificationMismatch] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind") or "").strip().lower()
        if kind not in _ALLOWED_KINDS:
            continue
        source_field = _optional_clip(entry.get("source_field"), _MISMATCH_FIELD_MAX_CHARS)
        catalog = _optional_clip(entry.get("catalog"), _MISMATCH_FIELD_MAX_CHARS)
        observed = _optional_clip(entry.get("observed"), _MISMATCH_FIELD_MAX_CHARS)
        if kind == KIND_INVENTED:
            source_field = None
            catalog = None
            if not observed:
                continue
        elif not source_field or not catalog or not observed:
            continue
        out.append(
            VerificationMismatch(
                kind=kind,
                source_field=source_field,
                catalog=catalog,
                observed=observed,
            )
        )
        if len(out) >= _MISMATCH_MAX:
            break
    return out


def _optional_clip(raw: Any, max_chars: int) -> str | None:
    if raw is None:
        return None
    text = _clip(str(raw).strip(), max_chars)
    return text or None


def _clip(text: str, max_chars: int) -> str:
    if max_chars < 1 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()
