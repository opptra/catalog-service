"""Post-render verification for IMAGE / A_PLUS slots.

The vision model scores the generated image on three axes:

- identity (hard) — same variant as source photos + catalog Color/Pack/silhouette
- claims (hard) — on-image text vs ``sku_master.attributes``
- quality (advisory) — crop, blur, unreadable type; shown, never retries

``confidence`` persisted for the UI is ``min(identity, claims)``. Omission is
allowed. Source photos are identity-only (capped). Retry is one-shot and can
be turned off with ``VERIFY_RETRY_ENABLED``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from core.clients.openrouter import OpenRouterClient
from core.config import settings
from pipelines.generation import tools
from utils.images import to_data_url, to_data_urls

# Change these constants to raise/lower the bar or skip auto re-render. Not env vars.
MIN_CONFIDENCE_PERCENT = 80
VERIFY_RETRY_ENABLED = False
SOURCE_PHOTO_LIMIT = 3

SCHEMA_VERSION = 2
STATUS_OK = "ok"
STATUS_ERROR = "error"
KIND_CONTRADICTION = "contradiction"
KIND_INVENTED = "invented"
KIND_IDENTITY = "identity"
KIND_QUALITY = "quality"
_ALLOWED_KINDS = frozenset({KIND_CONTRADICTION, KIND_INVENTED, KIND_IDENTITY, KIND_QUALITY})
_RETRY_KINDS = frozenset({KIND_CONTRADICTION, KIND_INVENTED, KIND_IDENTITY})

_VERIFY_MAX_TOKENS = 1600
_REASONING_MAX_CHARS = 800
_OBSERVED_MAX_ITEMS = 40
_OBSERVED_ITEM_MAX_CHARS = 120
_MISMATCH_MAX = 20
_MISMATCH_FIELD_MAX_CHARS = 200
_ERROR_MAX_CHARS = 200
_SLOT_FIELD_MAX_CHARS = 80


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
    identity: int | None = None
    claims: int | None = None
    quality: int | None = None
    reasoning: str | None = None
    observed_text: tuple[str, ...] = ()
    mismatches: tuple[VerificationMismatch, ...] = ()
    error: str | None = None
    attribute_name: str | None = None
    role: str | None = None
    kind: str | None = None

    def ship_score(self) -> int | None:
        """Badge / retry number: min of the hard axes, else stored confidence."""
        if self.identity is not None and self.claims is not None:
            return min(self.identity, self.claims)
        return self.confidence

    def below_threshold(self) -> bool:
        score = self.ship_score()
        return self.status == STATUS_OK and score is not None and score < MIN_CONFIDENCE_PERCENT

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
        score = self.ship_score()
        payload["confidence"] = 0 if score is None else score
        payload["threshold"] = MIN_CONFIDENCE_PERCENT
        payload["axes"] = {
            "identity": self.identity,
            "claims": self.claims,
            "quality": self.quality,
        }
        payload["reasoning"] = self.reasoning or ""
        payload["observed_text"] = list(self.observed_text)
        payload["mismatches"] = [item.to_json() for item in self.mismatches]
        slot: dict[str, Any] = {}
        if self.attribute_name:
            slot["name"] = self.attribute_name
        if self.role:
            slot["role"] = self.role
        if self.kind:
            slot["kind"] = self.kind
        if slot:
            payload["slot"] = slot
        return payload


def persist_payload(
    result: VerificationResult,
    *,
    previous: VerificationResult | None = None,
) -> dict[str, Any]:
    """JSONB written to ``sku_marketplace_attribute_value.verification``.

    When a mismatch retry actually ran, ``previous`` is the attempt-1 snapshot so
    the UI can still show why the first pass failed. Nested one level only.
    """
    payload = result.to_json()
    if previous is not None:
        payload["previous"] = previous.to_json()
    return payload


def error_result(*, model: str, attempt: int, error: str) -> VerificationResult:
    """Persistable failure when the verifier itself did not complete."""
    return VerificationResult(
        status=STATUS_ERROR,
        model=model,
        attempt=attempt,
        error=_clip(error, _ERROR_MAX_CHARS) or "verify_tool_call_failed",
    )


def should_retry(result: VerificationResult) -> bool:
    """True when the pipeline should re-render once for a hard-axis miss."""
    return VERIFY_RETRY_ENABLED and result.below_threshold()


def reference_image_urls(urls: list[str] | None) -> list[str]:
    """First ``SOURCE_PHOTO_LIMIT`` non-empty source photo URLs."""
    if not urls:
        return []
    out: list[str] = []
    for url in urls:
        text = str(url).strip()
        if text:
            out.append(text)
        if len(out) >= SOURCE_PHOTO_LIMIT:
            break
    return out


def retry_addendum(result: VerificationResult) -> str:
    """Ephemeral instructions for a one-shot re-render. Not stored on ``prompt``.

    Quality misses are omitted — they are advisory and must not trigger a redraw.
    """
    lines = [
        "The previous render failed product-data verification. Fix ONLY the issues below. "
        "Do not invent new product facts. PRODUCT DATA remains the only source of truth. "
        "Match the source photos for color, pack, print, and silhouette. "
        "Do not copy source-photo layout or overlays.",
        "",
        "Mismatches:",
    ]
    retry_items = [item for item in result.mismatches if item.kind in _RETRY_KINDS]
    if not retry_items:
        lines.append(
            f"- overall confidence {result.ship_score()}% was below {MIN_CONFIDENCE_PERCENT}%"
        )
    for item in retry_items:
        if item.kind == KIND_CONTRADICTION:
            lines.append(
                f'- contradiction: on-image "{item.observed}" vs catalog '
                f'{item.source_field}="{item.catalog}"'
            )
        elif item.kind == KIND_IDENTITY:
            if item.source_field and item.catalog:
                lines.append(
                    f'- identity: look "{item.observed}" vs catalog '
                    f'{item.source_field}="{item.catalog}" (match the source photos)'
                )
            else:
                lines.append(f'- identity: look "{item.observed}" does not match source photos')
        else:
            lines.append(
                f'- invented: on-image "{item.observed}" is in no PRODUCT DATA key or value'
            )
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
    source_image_urls: list[str] | None = None,
    attribute_name: str | None = None,
    role: str | None = None,
    kind: str | None = None,
    session_id: str | None = None,
) -> VerificationResult:
    """Score the generated image for identity (vs source photos) and claims (vs catalog)."""
    model = settings.openrouter_verify_model
    refs = reference_image_urls(source_image_urls)
    facts = _product_facts(product)
    prefix = (
        "=== PRODUCT DATA (authoritative — every key AND every value is a fact, "
        "including Description / title / bullets / care) ===\n"
        f"{json.dumps(facts, ensure_ascii=False, indent=2)}"
    )
    suffix = _verify_suffix(
        refs=refs,
        attribute_name=attribute_name,
        role=role,
        kind=kind,
    )
    parsed = client.call_tool(
        suffix,
        model=model,
        tool=tools.IMAGE_VERIFICATION_TOOL,
        image_urls=_chat_completion_image_urls(generated_image_url, refs),
        cache_prefix=prefix,
        max_tokens=_VERIFY_MAX_TOKENS,
        session_id=session_id,
    )
    return _parse_tool(
        parsed,
        model=model,
        attempt=attempt,
        attribute_name=attribute_name,
        role=role,
        kind=kind,
    )


def _verify_suffix(
    *,
    refs: list[str],
    attribute_name: str | None,
    role: str | None,
    kind: str | None,
) -> str:
    ref_n = len(refs)
    if ref_n:
        photo_line = (
            f"Image 1 is the GENERATED slot to score. Images 2–{ref_n + 1} are SOURCE "
            "product photos for identity only. Do not copy their layout or overlays."
        )
    else:
        photo_line = (
            "Image 1 is the GENERATED slot to score. No source photos are attached; "
            "score identity from PRODUCT DATA Color/Pack/silhouette only."
        )
    slot_lines = ["SLOT CONTEXT (not a source of product facts):"]
    slot_lines.append(f"- attribute={attribute_name or 'IMAGE'}")
    if role:
        slot_lines.append(f"- role={role}")
    if kind:
        slot_lines.append(f"- kind={kind}")
    slot_block = "\n".join(slot_lines)
    return (
        "You are marketplace image QA for one generated catalog slot "
        "(PDP gallery or A+). This image may go live. Prefer a miss over a silent ship.\n"
        f"{photo_line}\n"
        "Read every shopper-facing word, badge, and label on the generated image.\n\n"
        f"{slot_block}\n\n"
        "Score THREE axes (integers 0–100):\n"
        "- identity: same physical variant as the source photos and PRODUCT DATA "
        "Color / pack / print / silhouette. Size printed on the artwork is a CLAIMS "
        "issue, not identity. Lifestyle vs packshot is fine if it is the same product.\n"
        "- claims: on-image text vs the FULL PRODUCT DATA JSON — every key and every "
        "value, including long fields such as Description. Synonyms match "
        '("King Size" vs "King"). Omission is allowed — empty text can score high. '
        "Contradiction: on-image text fights a dedicated short field (Size, Color, Pack, "
        "etc.); that dedicated field wins even if Description disagrees. "
        "Invented: the claim (or a synonym) appears in NO key and NO value anywhere in "
        "PRODUCT DATA. If it appears in Description or any other value, it is NOT invented. "
        "Do not treat Description as marketing noise — search it. It is also a fact. "
        "Point it out when there is a contradiction between Description and the dedicated field. "
        "SKU, ASIN, UPC, EAN, or GTIN printed on the artwork is invented even if those "
        "ids exist in PRODUCT DATA.\n"
        "- quality: production fitness (crop, blur, unreadable type, junk props). "
        "Advisory only — do not let quality dominate identity or claims.\n\n"
        "mismatch kind: contradiction | invented | identity | quality. "
        "For identity, set source_field/catalog when the look fights a PRODUCT DATA key "
        "(e.g. Color). For quality, observed only.\n\n"
        "Call the submit_image_verification tool. Do not write JSON in the message body."
    )


def _chat_completion_image_urls(generated_image_url: str, refs: list[str]) -> list[str]:
    """Inline images for ``/chat/completions`` so OpenAI does not GET GCS itself."""
    generated = to_data_url(generated_image_url)
    if generated is None:
        raise ValueError("generated image could not be inlined for verification")
    return [generated, *to_data_urls(refs)]


def _product_facts(product: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in product.items() if key != "source_assets"}


def _parse_tool(
    parsed: dict[str, Any],
    *,
    model: str,
    attempt: int,
    attribute_name: str | None = None,
    role: str | None = None,
    kind: str | None = None,
) -> VerificationResult:
    if not isinstance(parsed, dict):
        raise ValueError("verification tool returned a non-object")
    identity = _clamp_confidence(parsed.get("identity"))
    claims = _clamp_confidence(parsed.get("claims"))
    quality = _optional_axis(parsed.get("quality"))
    reasoning = _clip(str(parsed.get("reasoning") or "").strip(), _REASONING_MAX_CHARS)
    observed = _parse_observed(parsed.get("observed_text"))
    mismatches = _parse_mismatches(parsed.get("mismatches"))
    return VerificationResult(
        status=STATUS_OK,
        model=model,
        attempt=attempt,
        confidence=min(identity, claims),
        identity=identity,
        claims=claims,
        quality=quality,
        reasoning=reasoning,
        observed_text=tuple(observed),
        mismatches=tuple(mismatches),
        attribute_name=_optional_clip(attribute_name, _SLOT_FIELD_MAX_CHARS),
        role=_optional_clip(role, _SLOT_FIELD_MAX_CHARS),
        kind=_optional_clip(kind, _SLOT_FIELD_MAX_CHARS),
    )


def _optional_axis(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        return _clamp_confidence(raw)
    except ValueError:
        return None


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
        if kind in {KIND_INVENTED, KIND_QUALITY}:
            source_field = None
            catalog = None
            if not observed:
                continue
        elif kind == KIND_IDENTITY:
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
