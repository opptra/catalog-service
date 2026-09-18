"""Stage 1: plan a coherent, non-duplicated image set for one attribute type per call.

IMAGE (PDP gallery) and A_PLUS are planned separately. Per job: build a SKU product
card (identity + unique facts) → select slots → assign unique fact ids → assemble a
sectioned per-slot brief (subject, CI scene, identity, overlay JSON, JSON DNA). That
brief is sent straight to the image model — no Scene rewrite step.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from core.clients.openrouter import OpenRouterClient
from core.config import settings
from core.exceptions import GalleryPlanError
from entities.catalog.attribute_enums import AttributeName
from pipelines.generation import common_image, tools
from pipelines.generation.context import GenerationContext

logger = logging.getLogger(__name__)

SECTION_TASK = "TASK"
SECTION_PRIORITY = "PRIORITY"
SECTION_SUBJECT = "SUBJECT"
SECTION_SLOT = "SLOT"
SECTION_SCENE = "SCENE"
SECTION_IDENTITY = "IDENTITY"
SECTION_OVERLAY_FACTS = "OVERLAY FACTS"
SECTION_JSON_DNA = "JSON DNA"
SECTION_FORBIDDEN = "FORBIDDEN"
SECTION_ORDER = (
    SECTION_TASK,
    SECTION_PRIORITY,
    SECTION_SUBJECT,
    SECTION_SLOT,
    SECTION_SCENE,
    SECTION_IDENTITY,
    SECTION_OVERLAY_FACTS,
    SECTION_JSON_DNA,
    SECTION_FORBIDDEN,
)
_SUBJECT_NAME_KEYS = ("title", "name", "product_name")


@dataclass(frozen=True, slots=True)
class SlotPlan:
    """One slot, ready for the image model.

    ``prompt`` is the assembled slot brief sent to the image model (subject,
    CI recipe, identity, owned facts, and JSON DNA). ``role`` / ``kind`` are CI
    slot fields passed to the verifier as context only. No separate Scene rewrite.
    """

    name: AttributeName
    slot: int
    prompt: str
    concept: str | None = None
    role: str | None = None
    kind: str | None = None


IDENTITY_ROLES = ("drop", "opening", "pack", "colour", "print", "mount")


@dataclass(frozen=True, slots=True)
class ProductIdentity:
    """Hang/geometry constraints. Never overlay copy."""

    drop: str = ""
    opening: str = ""
    pack: str = ""
    colour: str = ""
    print_name: str = ""
    mount: str = ""

    def to_json(self) -> dict[str, str]:
        mapping = {
            "drop": self.drop,
            "opening": self.opening,
            "pack": self.pack,
            "colour": self.colour,
            "print": self.print_name,
            "mount": self.mount,
        }
        return {key: value for key, value in mapping.items() if value}


@dataclass(frozen=True, slots=True)
class CardFact:
    """One unique overlay-eligible fact. ``fact_id`` is assigned in code."""

    fact_id: str
    claim: str
    value: str
    field: str


@dataclass(frozen=True, slots=True)
class ProductCard:
    """Canonical SKU truth for image planning, briefs, and QA."""

    identity: ProductIdentity
    facts: tuple[CardFact, ...]


@dataclass(frozen=True, slots=True)
class AssignedFact:
    """One overlay fact. ``value`` is the callout; ``field`` is context; ``claim`` is CI-only."""

    claim: str
    value: str
    field: str


@dataclass(frozen=True, slots=True)
class AllocatedSlot:
    slot_def: dict[str, Any]
    concept: str
    owned_claims: list[str]
    assigned_facts: list[AssignedFact]


def _plan_model() -> str:
    """Model for structured planning/extraction (product card, leftover assignment)."""
    return settings.openrouter_text_model


def _track_key(name: AttributeName) -> str:
    if name == AttributeName.IMAGE:
        return "gallery"
    if name == AttributeName.A_PLUS:
        return "aplus"
    return str(name.value).lower()


def _slot_order_key(slot: dict[str, Any]) -> int:
    order = slot.get("order")
    return order if isinstance(order, int) else 10**9


def _dup_key(slot: dict[str, Any]) -> str:
    owns = slot.get("owns")
    if isinstance(owns, str) and owns.strip():
        return owns.strip()
    role = slot.get("role")
    if isinstance(role, str) and role.strip():
        return role.strip()
    order = slot.get("order")
    if isinstance(order, int):
        return f"order:{order}"
    return json.dumps(slot, ensure_ascii=False, sort_keys=True)[:200]


def _candidate_ci_slots(ctx: GenerationContext, name: AttributeName) -> list[dict[str, Any]]:
    raw_plan = ctx.category_intelligence.get("image_plan")
    if not isinstance(raw_plan, dict):
        raise GalleryPlanError("category_intelligence.image_plan missing or not an object")

    track_key = _track_key(name)
    track = raw_plan.get(track_key)
    if not isinstance(track, dict):
        raise GalleryPlanError(f"category_intelligence.image_plan.{track_key} missing")

    slots_raw = track.get("slots")
    if not isinstance(slots_raw, list):
        raise GalleryPlanError(f"category_intelligence.image_plan.{track_key}.slots missing")

    slots = [s for s in slots_raw if isinstance(s, dict)]
    core = sorted(
        (s for s in slots if str(s.get("priority", "")).lower() == "core"),
        key=_slot_order_key,
    )
    extended = sorted(
        (s for s in slots if str(s.get("priority", "")).lower() != "core"),
        key=_slot_order_key,
    )
    return core + extended


def _feature_priority(slot: dict[str, Any]) -> list[str]:
    raw = slot.get("feature_priority")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def _max_callouts(slot: dict[str, Any]) -> int:
    raw = slot.get("max_callouts")
    return raw if isinstance(raw, int) and raw >= 0 else 0


def _slot_text_field(slot: dict[str, Any], key: str) -> str:
    raw = slot.get(key)
    return raw.strip() if isinstance(raw, str) and raw.strip() else ""


def _slot_concept(slot: dict[str, Any]) -> str:
    role = _slot_text_field(slot, "role")
    if role:
        return role
    content = _slot_text_field(slot, "content")
    if content:
        return content.split(".", 1)[0].strip() or content[:80]
    return "catalog shot"


def _normalize_value(value: str) -> str:
    return " ".join(value.casefold().split())


def _product_data_dump(product: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in product.items() if key != "source_assets"}


def _subject_category(category_intelligence: dict[str, Any]) -> str:
    meta = category_intelligence.get("meta")
    if not isinstance(meta, dict):
        return ""
    value = meta.get("category")
    if not isinstance(value, str):
        return ""
    return value.strip()


def _subject_name(product: dict[str, Any]) -> str:
    for key in _SUBJECT_NAME_KEYS:
        value = product.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _subject_lines(
    *,
    category_path: tuple[str, ...] = (),
    category: str = "",
    name: str = "",
) -> list[str]:
    path = " > ".join(part.strip() for part in category_path if part.strip())
    category_label = category.strip()
    name_label = name.strip()
    if not path and not category_label and not name_label:
        return ["(none)"]
    lines = [
        "Not overlay copy. Do not paint these words. Use them only to know what "
        "the attached photos are.",
    ]
    if path:
        lines.append(f"Category path: {path}")
    elif category_label:
        lines.append(f"Category: {category_label}")
    if name_label:
        lines.append(f"Name: {name_label}")
    return lines


def collect_feature_priority_claims(
    ctx: GenerationContext, names: list[AttributeName]
) -> list[str]:
    """Unique CI feature_priority strings across the requested image tracks."""
    claims: list[str] = []
    for name in names:
        try:
            for slot in _candidate_ci_slots(ctx, name):
                claims.extend(_feature_priority(slot))
        except GalleryPlanError:
            logger.info("skip claims for %s: image_plan track missing", name.value)
    return sorted(set(claims))


def _product_card_prompt(product: dict[str, Any]) -> str:
    facts = _product_data_dump(product)
    return (
        "You build identity and unique overlay facts for catalog image generation "
        "from this SKU's PRODUCT DATA only. Do not attach CI claims.\n"
        "\n"
        "IDENTITY (geometry object, never overlay copy):\n"
        "- Return drop, opening, pack, colour, print, and mount when PRODUCT DATA "
        "has them. Values are verbatim snippets. Omit a key when PRODUCT DATA has "
        "no supporting snippet.\n"
        "- drop is how long or large the product hangs or sits. opening is the "
        "aperture this product is made for (window vs door or any equivalent named "
        "in PRODUCT DATA) — not a restyled room. pack, colour, print, and mount "
        "are how the product looks.\n"
        "- Copy verbatim substrings. Never invent. Do not convert units.\n"
        "- If the same spec also appears in facts, copy the same snippet (same unit "
        "system) into both. Do not put feet in identity and centimetres in facts "
        "for the same drop.\n"
        "\n"
        "FACTS (unique overlay-eligible snippets):\n"
        "- PRODUCT DATA is the only source of facts.\n"
        "- Across the whole facts list, one shopper fact may appear only once. If two "
        "items would paint the same information (same count, size, material, or "
        "inclusion restated in other words), keep the more specific structured field "
        "and omit the restatement entirely.\n"
        "- Independent specs stay as separate items (colour vs print, length vs width).\n"
        "- Prefer a short structured field over a marketing paragraph. Shorten at source "
        '(e.g. water temperature → "Machine Wash Cold", not the whole wash-care sentence).\n'
        '- If the cell is already short ("210", "Microfiber"), leave it. Do not expand '
        '"210" into "210 TC". Do not convert units (never "7 feet" → "210 cm" / "84 in").\n'
        "- If the cell already includes a unit, copy that unit with the number "
        '("7 feet" stays "7 feet").\n'
        "- Do not pair a feet/inch Size with a centimetre Length/Width (or kg with lb) "
        "for the same spec. If Size is in one system and structured Length/Width share "
        "another, prefer the structured pair that already shares a unit; omit Size "
        "rather than mixing systems. Identity drop/opening and facts for that same spec "
        "must share that unit system too.\n"
        "- If PRODUCT DATA names more than one independent spec (e.g. cover length and "
        "cover width), return ONE fact per spec with different values.\n"
        "- Every value must be a verbatim substring of PRODUCT DATA.\n"
        "- field is a short name for this fact so an incomplete value can be understood. "
        "It is not overlay copy. When the PRODUCT DATA key already names this spec, copy "
        "that key as field. When the key is a generic copy container that does not name "
        "this spec, do not copy that key; give field a short name for this spec. "
        "field must not be empty.\n"
        "- Do not return empty-value rows.\n"
        "\n"
        "PRODUCT DATA (opaque strings/columns):\n"
        f"{json.dumps(facts, ensure_ascii=False, indent=2)}\n"
    )


def _fact_claim_tags_prompt(facts: list[CardFact], claims: list[str]) -> str:
    payload = [
        {"fact_id": fact.fact_id, "field": fact.field, "value": fact.value} for fact in facts
    ]
    return (
        "Tag each existing unique overlay fact with at most one CLAIMS string.\n"
        "- Support is meaning, not identical wording — the field or value may use "
        "different words than the claim. Copy that CLAIMS string onto claim exactly "
        "(same spelling and punctuation).\n"
        "- Each fact_id at most once. Do not add, split, or clone facts. Two claims "
        "must not clone one fact.\n"
        "- If no CLAIMS string fits a fact, omit it or leave claim empty.\n"
        "- If several CLAIMS strings fit one fact, pick the single best meaning fit.\n"
        "\n"
        "FACTS:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
        "\n"
        "CLAIMS (feature_priority strings — bind each fact by meaning): "
        f"{json.dumps(claims, ensure_ascii=False)}\n"
    )


def _parse_identity(raw: Any) -> ProductIdentity:
    if not isinstance(raw, dict):
        return ProductIdentity()
    cleaned: dict[str, str] = {}
    for key in IDENTITY_ROLES:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            cleaned[key] = value.strip()
    return ProductIdentity(
        drop=cleaned.get("drop", ""),
        opening=cleaned.get("opening", ""),
        pack=cleaned.get("pack", ""),
        colour=cleaned.get("colour", ""),
        print_name=cleaned.get("print", ""),
        mount=cleaned.get("mount", ""),
    )


def _parse_card_facts(raw: Any) -> list[CardFact]:
    if not isinstance(raw, list):
        return []
    out: list[CardFact] = []
    seen: set[str] = set()
    next_id = 1
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        field = entry.get("field")
        value = entry.get("value")
        if not isinstance(field, str) or not isinstance(value, str):
            continue
        heading = field.strip()
        cleaned = value.strip()
        if not heading or not cleaned:
            continue
        norm = _normalize_value(cleaned)
        if norm in seen:
            logger.info(
                "product card drop fact field=%r value=%r reason=duplicate_shopper_fact",
                heading,
                cleaned,
            )
            continue
        seen.add(norm)
        out.append(
            CardFact(
                fact_id=f"f{next_id}",
                claim="",
                value=cleaned,
                field=heading,
            )
        )
        next_id += 1
    return out


def _apply_claim_tags(
    facts: list[CardFact],
    raw: Any,
    *,
    allowed_claims: set[str],
) -> list[CardFact]:
    if not facts:
        return facts
    tags = raw.get("tags") if isinstance(raw, dict) else None
    if not isinstance(tags, list):
        return facts
    known = {fact.fact_id: fact for fact in facts}
    claimed: dict[str, str] = {}
    used_ids: set[str] = set()
    for entry in tags:
        if not isinstance(entry, dict):
            continue
        fact_id = entry.get("fact_id")
        if not isinstance(fact_id, str) or fact_id not in known or fact_id in used_ids:
            continue
        used_ids.add(fact_id)
        raw_claim = entry.get("claim")
        claim = raw_claim.strip() if isinstance(raw_claim, str) else ""
        if claim and claim not in allowed_claims:
            logger.info("product card unlink claim=%r reason=not_in_ci_list", claim)
            claim = ""
        claimed[fact_id] = claim
    return [
        CardFact(
            fact_id=fact.fact_id,
            claim=claimed.get(fact.fact_id, ""),
            value=fact.value,
            field=fact.field,
        )
        for fact in facts
    ]


def build_product_card(
    client: OpenRouterClient,
    ctx: GenerationContext,
    *,
    claims: list[str],
    session_id: str | None,
) -> ProductCard:
    """One SKU card: unique facts first, then at most one claim tag per fact."""
    parsed = client.call_tool(
        _product_card_prompt(ctx.product),
        model=_plan_model(),
        tool=tools.gallery_product_card_tool(),
        max_tokens=4096,
        session_id=session_id,
    )
    if not isinstance(parsed, dict):
        raise GalleryPlanError("product card missing object payload")
    identity = _parse_identity(parsed.get("identity"))
    facts = _parse_card_facts(parsed.get("facts"))
    if facts and claims:
        tagged = client.call_tool(
            _fact_claim_tags_prompt(facts, claims),
            model=_plan_model(),
            tool=tools.gallery_fact_claim_tags_tool(),
            max_tokens=2048,
            session_id=session_id,
        )
        facts = _apply_claim_tags(facts, tagged, allowed_claims=set(claims))
    if not identity.to_json():
        logger.info("product card identity empty")
    if not facts:
        logger.info("product card facts empty")
    return ProductCard(identity=identity, facts=tuple(facts))


def product_card_payload(card: ProductCard | None) -> dict[str, Any]:
    """JSON for QA: identity geometry + unique facts (no CI claim strings)."""
    if card is None:
        return {"identity": {}, "unique_facts": []}
    return {
        "identity": card.identity.to_json(),
        "unique_facts": [{"field": fact.field, "value": fact.value} for fact in card.facts],
    }


def empty_product_card() -> ProductCard:
    return ProductCard(identity=ProductIdentity(), facts=())


def _slot_usable(*, slot: dict[str, Any], has_overlay_facts: bool) -> bool:
    """Callout slots need at least one unique card fact on the SKU; else skip.

    Heroes with max_callouts 0 stay eligible. Overlay slots stay eligible when
    the product card has unique facts, even if a CI claim string did not match.
    """
    if _max_callouts(slot) <= 0:
        return True
    return has_overlay_facts


def _select_slots(
    candidate_slots: list[dict[str, Any]],
    *,
    quantity: int,
    has_overlay_facts: bool,
) -> list[dict[str, Any]]:
    """Select exactly ``quantity`` slots (dedupe by owns; keep overlays when facts exist).

    Unique owns/role keys are taken first. When that palette is shorter than
    ``quantity`` (CI often repeats a hero role without ``owns``), leftover
    unused candidates fill the remaining slots so the job does not fail.
    Overlay slots with max_callouts > 0 are skipped only when the SKU has no
    unique overlay facts. Duplicate heroes fill last, after unused overlay slots.
    """
    selected: list[dict[str, Any]] = []
    used_keys: set[str] = set()
    used_indexes: set[int] = set()

    def _add(index: int, slot: dict[str, Any]) -> None:
        selected.append(slot)
        used_keys.add(_dup_key(slot))
        used_indexes.add(index)

    for index, slot in enumerate(candidate_slots):
        if len(selected) >= quantity:
            break
        if _dup_key(slot) in used_keys:
            continue
        if not _slot_usable(slot=slot, has_overlay_facts=has_overlay_facts):
            continue
        _add(index, slot)

    if len(selected) < quantity:
        for index, slot in enumerate(candidate_slots):
            if len(selected) >= quantity:
                break
            if index in used_indexes or _dup_key(slot) in used_keys:
                continue
            if not _slot_usable(slot=slot, has_overlay_facts=has_overlay_facts):
                continue
            _add(index, slot)

    if len(selected) < quantity:
        for index, slot in enumerate(candidate_slots):
            if len(selected) >= quantity:
                break
            if index in used_indexes:
                continue
            if not _slot_usable(slot=slot, has_overlay_facts=has_overlay_facts):
                continue
            _add(index, slot)

    if len(selected) != quantity:
        raise GalleryPlanError(
            f"slot selection produced {len(selected)}/{quantity} slots for {candidate_slots=}"
        )
    return selected


def _facts_for_owned(
    owned: list[CardFact],
    *,
    limit: int | None = None,
) -> list[AssignedFact]:
    """Convert owned card facts into overlay items, capped at ``limit`` values."""
    out: list[AssignedFact] = []
    seen_values: set[str] = set()
    for item in owned:
        if limit is not None and len(out) >= limit:
            logger.info(
                "facts cap fact_id=%r value=%r reason=max_callouts_%s",
                item.fact_id,
                item.value,
                limit,
            )
            return out
        norm = _normalize_value(item.value)
        if norm in seen_values:
            continue
        seen_values.add(norm)
        out.append(AssignedFact(claim=item.claim, value=item.value, field=item.field.strip()))
    return out


def _own_card_facts_for_slots(
    *,
    chosen_slots: list[dict[str, Any]],
    card: ProductCard,
) -> list[list[CardFact]]:
    """First pass: CI feature_priority ∩ card facts linked to that claim.

    ``max_callouts`` is a paint budget (number of values). Earlier slots win
    unique fact_ids.
    """
    owned_by_slot: list[list[CardFact]] = []
    used_ids: set[str] = set()
    by_claim: dict[str, list[CardFact]] = {}
    for fact in card.facts:
        if fact.claim:
            by_claim.setdefault(fact.claim, []).append(fact)

    for slot_index, slot_def in enumerate(chosen_slots):
        cap = _max_callouts(slot_def)
        kept: list[CardFact] = []
        for claim in _feature_priority(slot_def):
            if cap >= 0 and len(kept) >= cap:
                break
            for fact in by_claim.get(claim, []):
                if cap >= 0 and len(kept) >= cap:
                    break
                if fact.fact_id in used_ids:
                    logger.info(
                        "ownership skip fact_id=%r claim=%r slot=%s reason=already_owned",
                        fact.fact_id,
                        claim,
                        slot_index + 1,
                    )
                    continue
                used_ids.add(fact.fact_id)
                kept.append(fact)
        owned_by_slot.append(kept)
    return owned_by_slot


def _remaining_priority_claims(slot: dict[str, Any], owned: list[CardFact]) -> list[str]:
    have = {fact.claim for fact in owned if fact.claim}
    return [claim for claim in _feature_priority(slot) if claim not in have]


def _sort_owned_by_priority(slot: dict[str, Any], owned: list[CardFact]) -> list[CardFact]:
    rank = {claim: index for index, claim in enumerate(_feature_priority(slot))}
    return [
        fact
        for _, fact in sorted(
            enumerate(owned),
            key=lambda item: (rank.get(item[1].claim, 10**6), item[0]),
        )
    ]


def _bind_priority_prompt(
    *,
    chosen_slots: list[dict[str, Any]],
    owned_by_slot: list[list[CardFact]],
    unused: list[CardFact],
    slot_indexes: list[int],
) -> str:
    slots_payload = []
    for index in slot_indexes:
        slot = chosen_slots[index]
        cap = _max_callouts(slot)
        owned = owned_by_slot[index]
        slots_payload.append(
            {
                "slot_index": index + 1,
                "role": _slot_text_field(slot, "role"),
                "kind": _slot_text_field(slot, "kind"),
                "remaining_budget": max(0, cap - len(owned)),
                "remaining_claims": _remaining_priority_claims(slot, owned),
            }
        )
    facts_payload = [
        {
            "fact_id": fact.fact_id,
            "field": fact.field,
            "value": fact.value,
            "claim": fact.claim,
        }
        for fact in unused
    ]
    return (
        "Attach unused unique overlay facts to overlay slots by walking each slot's "
        "remaining_claims (CI feature_priority that still has no fact).\n"
        "- Copy claim exactly from that slot's remaining_claims. Do not shorten or "
        "paraphrase the claim string.\n"
        "- Support is meaning, not identical wording — field or value may use "
        "different words than the claim.\n"
        "- Each fact_id at most once. Two claims must not clone one fact.\n"
        "- Fill earlier remaining_claims first. Do not exceed remaining_budget.\n"
        "- Do not invent facts. Skip rather than assign a fact to a claim it does "
        "not support.\n"
        "- Do not assign a fact to a slot unless claim is in that slot's "
        "remaining_claims. A care or cleaning fact belongs only on a slot that "
        "lists that claim.\n\n"
        f"SLOTS:\n{json.dumps(slots_payload, ensure_ascii=False, indent=2)}\n\n"
        f"UNUSED FACTS:\n{json.dumps(facts_payload, ensure_ascii=False, indent=2)}\n"
    )


def _apply_priority_bindings(
    *,
    chosen_slots: list[dict[str, Any]],
    owned_by_slot: list[list[CardFact]],
    unused: list[CardFact],
    parsed: dict[str, Any],
    allowed_indexes: list[int],
) -> list[list[CardFact]]:
    unused_by_id = {fact.fact_id: fact for fact in unused}
    filled = [list(owned) for owned in owned_by_slot]
    allowed = set(allowed_indexes)
    remaining_for = {
        index: set(_remaining_priority_claims(chosen_slots[index], filled[index]))
        for index in allowed_indexes
    }
    raw = parsed.get("assignments") if isinstance(parsed, dict) else None
    if not isinstance(raw, list):
        return filled
    taken: set[str] = set()
    used_claims: dict[int, set[str]] = {index: set() for index in allowed_indexes}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        fact_id = entry.get("fact_id")
        slot_index = entry.get("slot_index")
        raw_claim = entry.get("claim")
        if not isinstance(fact_id, str) or not isinstance(slot_index, int):
            continue
        claim = raw_claim.strip() if isinstance(raw_claim, str) else ""
        fact = unused_by_id.get(fact_id)
        if fact is None or fact_id in taken or not claim:
            continue
        position = slot_index - 1
        if position not in allowed:
            continue
        cap = _max_callouts(chosen_slots[position])
        if cap <= 0 or len(filled[position]) >= cap:
            continue
        if claim not in remaining_for.get(position, set()):
            continue
        if claim in used_claims[position]:
            continue
        taken.add(fact_id)
        used_claims[position].add(claim)
        remaining_for[position].discard(claim)
        filled[position].append(
            CardFact(
                fact_id=fact.fact_id,
                claim=claim,
                value=fact.value,
                field=fact.field,
            )
        )
    return filled


def _bind_priority_facts(
    *,
    chosen_slots: list[dict[str, Any]],
    owned_by_slot: list[list[CardFact]],
    card: ProductCard,
    client: Any = None,
    session_id: str | None = None,
) -> list[list[CardFact]]:
    """Meaning-bind unused facts onto remaining feature_priority claims (exact strings)."""
    if client is None:
        return owned_by_slot
    unused = _unused_facts(card, owned_by_slot)
    need: list[int] = []
    for index, slot in enumerate(chosen_slots):
        cap = _max_callouts(slot)
        owned = owned_by_slot[index]
        if cap <= 0 or len(owned) >= cap:
            continue
        if _remaining_priority_claims(slot, owned):
            need.append(index)
    if not unused or not need:
        return owned_by_slot
    try:
        parsed = client.call_tool(
            _bind_priority_prompt(
                chosen_slots=chosen_slots,
                owned_by_slot=owned_by_slot,
                unused=unused,
                slot_indexes=need,
            ),
            model=_plan_model(),
            tool=tools.gallery_bind_slot_claims_tool(),
            max_tokens=2048,
            session_id=session_id,
        )
        filled = _apply_priority_bindings(
            chosen_slots=chosen_slots,
            owned_by_slot=owned_by_slot,
            unused=unused,
            parsed=parsed if isinstance(parsed, dict) else {},
            allowed_indexes=need,
        )
    except Exception:  # noqa: BLE001 — exact-match ownership still stands
        logger.exception("priority claim bind failed; keeping exact-match facts")
        return owned_by_slot
    return filled


def _empty_overlay_indexes(
    chosen_slots: list[dict[str, Any]], owned_by_slot: list[list[CardFact]]
) -> list[int]:
    """Overlay slots that still have no facts after first-pass claim ownership.

    Leftover fill may seed these so they do not fall into the paint-no-specs
    branch. Slots that already own a claim-matched fact are not padded.
    """
    empty: list[int] = []
    for index, (slot_def, owned) in enumerate(zip(chosen_slots, owned_by_slot, strict=True)):
        if _max_callouts(slot_def) > 0 and not owned:
            empty.append(index)
    return empty


def _unused_facts(card: ProductCard, owned_by_slot: list[list[CardFact]]) -> list[CardFact]:
    used = {fact.fact_id for owned in owned_by_slot for fact in owned}
    return [fact for fact in card.facts if fact.fact_id not in used]


def _fill_leftover_fifo(
    chosen_slots: list[dict[str, Any]],
    owned_by_slot: list[list[CardFact]],
    unused: list[CardFact],
    *,
    allowed_indexes: list[int],
) -> list[list[CardFact]]:
    """Give leftover unique facts to overlay slots that started with none."""
    remaining = list(unused)
    filled = [list(owned) for owned in owned_by_slot]
    for index in allowed_indexes:
        cap = _max_callouts(chosen_slots[index])
        if cap <= 0:
            continue
        while remaining and len(filled[index]) < cap:
            filled[index].append(remaining.pop(0))
    return filled


def _assign_leftover_prompt(
    *,
    chosen_slots: list[dict[str, Any]],
    empty_indexes: list[int],
    unused: list[CardFact],
    owned_by_slot: list[list[CardFact]],
) -> str:
    slots_payload = []
    for index in empty_indexes:
        slot = chosen_slots[index]
        cap = _max_callouts(slot)
        slots_payload.append(
            {
                "slot_index": index + 1,
                "role": _slot_text_field(slot, "role"),
                "kind": _slot_text_field(slot, "kind"),
                "content": _slot_text_field(slot, "content"),
                "pattern": _slot_text_field(slot, "pattern"),
                "feature_priority": _feature_priority(slot),
                "remaining_budget": max(0, cap - len(owned_by_slot[index])),
            }
        )
    facts_payload = [
        {
            "fact_id": fact.fact_id,
            "field": fact.field,
            "value": fact.value,
            "claim": fact.claim,
        }
        for fact in unused
    ]
    return (
        "Assign unused unique overlay facts to overlay slots that still have no "
        "facts. Prefer facts that support a claim in this slot's feature_priority "
        "(meaning, not identical wording). Copy no new facts. Each fact_id at most "
        "once. Do not exceed remaining_budget. Skip a fact rather than force a poor "
        "fit. Do not assign to any slot that is not in SLOTS. Do not assign a care "
        "or cleaning fact unless that claim is on this slot's feature_priority. Do "
        "not pad a slot that already has facts.\n\n"
        f"SLOTS:\n{json.dumps(slots_payload, ensure_ascii=False, indent=2)}\n\n"
        f"UNUSED FACTS:\n{json.dumps(facts_payload, ensure_ascii=False, indent=2)}\n"
    )


def _apply_tool_assignments(
    *,
    chosen_slots: list[dict[str, Any]],
    owned_by_slot: list[list[CardFact]],
    unused: list[CardFact],
    parsed: dict[str, Any],
    allowed_indexes: list[int],
) -> list[list[CardFact]]:
    unused_by_id = {fact.fact_id: fact for fact in unused}
    filled = [list(owned) for owned in owned_by_slot]
    allowed = set(allowed_indexes)
    raw = parsed.get("assignments") if isinstance(parsed, dict) else None
    if not isinstance(raw, list):
        return filled
    taken: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        fact_id = entry.get("fact_id")
        slot_index = entry.get("slot_index")
        if not isinstance(fact_id, str) or not isinstance(slot_index, int):
            continue
        fact = unused_by_id.get(fact_id)
        if fact is None or fact_id in taken:
            continue
        position = slot_index - 1
        if position not in allowed:
            continue
        cap = _max_callouts(chosen_slots[position])
        if cap <= 0 or len(filled[position]) >= cap:
            continue
        taken.add(fact_id)
        filled[position].append(fact)
    return filled


def _fill_leftover_facts(
    *,
    chosen_slots: list[dict[str, Any]],
    owned_by_slot: list[list[CardFact]],
    card: ProductCard,
    client: Any = None,
    session_id: str | None = None,
) -> list[list[CardFact]]:
    unused = _unused_facts(card, owned_by_slot)
    empty = _empty_overlay_indexes(chosen_slots, owned_by_slot)
    if not unused or not empty:
        return owned_by_slot

    filled = owned_by_slot
    if client is not None:
        try:
            parsed = client.call_tool(
                _assign_leftover_prompt(
                    chosen_slots=chosen_slots,
                    empty_indexes=empty,
                    unused=unused,
                    owned_by_slot=owned_by_slot,
                ),
                model=_plan_model(),
                tool=tools.gallery_assign_slot_facts_tool(),
                max_tokens=2048,
                session_id=session_id,
            )
            filled = _apply_tool_assignments(
                chosen_slots=chosen_slots,
                owned_by_slot=owned_by_slot,
                unused=unused,
                parsed=parsed if isinstance(parsed, dict) else {},
                allowed_indexes=empty,
            )
        except Exception:  # noqa: BLE001 — FIFO keeps empty overlay slots from going blank
            logger.exception("leftover fact assignment failed; filling in slot order")
            filled = owned_by_slot

    leftover = _unused_facts(card, filled)
    return _fill_leftover_fifo(chosen_slots, filled, leftover, allowed_indexes=empty)


def _allocate_slots(
    *,
    chosen_slots: list[dict[str, Any]],
    card: ProductCard,
    client: Any = None,
    session_id: str | None = None,
) -> list[AllocatedSlot]:
    """Map chosen CI slots to unique card facts (claim pass, then leftover fill)."""
    owned_by_slot = _own_card_facts_for_slots(chosen_slots=chosen_slots, card=card)
    owned_by_slot = _bind_priority_facts(
        chosen_slots=chosen_slots,
        owned_by_slot=owned_by_slot,
        card=card,
        client=client,
        session_id=session_id,
    )
    owned_by_slot = _fill_leftover_facts(
        chosen_slots=chosen_slots,
        owned_by_slot=owned_by_slot,
        card=card,
        client=client,
        session_id=session_id,
    )
    allocated: list[AllocatedSlot] = []
    for slot_def, owned in zip(chosen_slots, owned_by_slot, strict=True):
        allocated.append(
            AllocatedSlot(
                slot_def=slot_def,
                concept=_slot_concept(slot_def),
                owned_claims=list(dict.fromkeys(fact.claim for fact in owned if fact.claim)),
                assigned_facts=_facts_for_owned(
                    _sort_owned_by_priority(slot_def, owned),
                    limit=_max_callouts(slot_def),
                ),
            )
        )
    return allocated


def _overlay_value(value: str) -> str:
    """Painted label: first letter uppercase, remaining characters unchanged."""
    for i, ch in enumerate(value):
        if ch.isalpha():
            if ch.islower():
                return f"{value[:i]}{ch.upper()}{value[i + 1 :]}"
            return value
    return value


def _facts_block(assigned_facts: list[AssignedFact]) -> str:
    """JSON list of assigned facts for the image-model brief."""
    if not assigned_facts:
        return "[]"
    payload = [
        {
            "claim": fact.claim,
            "field": fact.field,
            "value": _overlay_value(fact.value),
        }
        for fact in assigned_facts
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _identity_block(identity: ProductIdentity) -> str:
    payload = identity.to_json()
    return json.dumps(payload, ensure_ascii=False, indent=2) if payload else "{}"


def _overlay_rules_when_facts(assigned_facts: list[AssignedFact]) -> list[str]:
    budget = len(assigned_facts)
    return [
        f"On-image text budget: {budget} item(s). Create exactly one overlay "
        "callout for each facts JSON object. Do not add another overlay from "
        "Content, Pattern, Slot, JSON DNA, or source-photo badges and size tags. "
        "Letters printed on the physical product are identity, not extra budget "
        "items.",
        "This shot has required on-image facts as JSON below. Render every fact "
        "visibly and legibly in the finished image. Do not paint two overlays that "
        "restate the same shopper fact.",
        'Each object\'s "value" is the on-image callout.',
        '"field" names what the value is. A shopper reading the overlay must '
        "clearly understand what this fact is about. You may use field and value "
        "in one overlay to make that context, not as two separate labels. If "
        "field would only repeat the value, do not use it. Do not paint claim.",
        "Units stay with the fact. If value already contains a unit, that is the "
        "only unit for that fact — do not add a converted equivalent in another "
        "system, in a table, on a label, or in parentheses.",
        "If value is a bare number and field names a unit, show that same unit "
        "beside the number. Never attach a different unit.",
        "Do not invent a different number, unit, or fact. Do not add extra "
        "measurements that are not in this facts JSON.",
        'Do not paint "claim", JSON keys, braces, or quotes.',
        "Overlay information may come only from the facts JSON. Visible overlay "
        "text comes from the value, using field in the same overlay when that "
        "makes the fact clear. Do not paint field and value as two labels. Do not "
        "paint claim. Do not introduce any information that is not supported by "
        "the facts JSON.",
        "Only the facts JSON may determine overlay claims and information.",
        "Do not invent unsupported specifications, claims, or marketing copy. "
        "Do not add related instruction icons or extra care rows that are not in "
        "this facts JSON.",
        "Do not draw dimension arrows, tape-measure lines, or measurement rulers. "
        "Overlay values appear as labels, not as diagrams on the product. Numerals "
        "and units count as overlay chrome.",
        "Integrate the text as a restrained catalog-style overlay in a readable "
        "area without changing drop, opening, or hang from IDENTITY and the "
        "source photos.",
        _facts_block(assigned_facts),
    ]


def _overlay_rules_when_empty() -> list[str]:
    return [
        "[]",
        "This shot has no on-image facts. Paint no product specs, slogans, size "
        "charts, icon strips, captions, or promotional copy. Keep letters that "
        "are physically on the product.",
        "Empty facts JSON means no overlay chrome — not a blank product. Keep "
        "on-product lettering, woven marks, and print from the reference photos.",
    ]


def _slot_prompt(
    *,
    slot: dict[str, Any],
    assigned_facts: list[AssignedFact],
    brand_look: str,
    identity: ProductIdentity | None = None,
    category: str = "",
    name: str = "",
    category_path: tuple[str, ...] = (),
) -> str:
    """Assemble the sectioned image-model brief for one slot (no Scene rewrite)."""
    role = _slot_text_field(slot, "role")
    kind = _slot_text_field(slot, "kind")
    content = _slot_text_field(slot, "content")
    pattern = _slot_text_field(slot, "pattern")
    slot_line = " — ".join(part for part in (role, kind) if part) or "catalog shot"
    identity_obj = identity or ProductIdentity()

    lines = [
        SECTION_TASK,
        "Create this image from the product reference photos attached to this call.",
        "",
        SECTION_PRIORITY,
        "Kind of product: the SUBJECT line (not overlay copy).",
        "Geometry: attached photos + the IDENTITY object. Scale the architectural "
        "opening to the product; do not enlarge the opening so the product looks "
        "floor-length. Geometry outranks SCENE and OVERLAY — callout layout must "
        "not stretch hang or opening height.",
        "On-image text: the OVERLAY FACTS list only.",
        "Scene: Content / Pattern, without changing geometry or adding text. "
        "Steps or guidance in Pattern are layout only — do not invent extra "
        "instruction labels to fill the sequence.",
        "Styling: JSON DNA for overlay chrome only.",
        "",
        SECTION_SUBJECT,
        *_subject_lines(
            category_path=category_path,
            category=category,
            name=name,
        ),
        "",
        SECTION_SLOT,
        slot_line,
        "",
        SECTION_SCENE,
        "Content and Pattern describe the shot: room, lighting, mood, cutaway, and "
        "how the product sits. They are not copy to typeset — never paint any word "
        "from Slot, SUBJECT, Content, Pattern, or JSON DNA onto the artwork as "
        "overlay chrome.",
        f"Content (composition only — not on-image copy): {content or '(none)'}",
        f"Pattern (composition only — not on-image copy): {pattern or '(none)'}",
        "If Pattern asks for measurement marks, diagrams, or a sizing area, place "
        "the OVERLAY FACTS labels only. Do not add numbers, arrows, rulers, or "
        "specs from IDENTITY or source photos.",
        "If Content or Pattern asks for steps, guidance, care, or a sequence, that "
        "is layout only. Do not invent extra instruction labels, icons, or claims "
        "to fill that sequence. The only shopper-facing instruction text is "
        "OVERLAY FACTS.",
        "Restyle furniture and light if needed, but keep the opening height vs "
        "floor and ceiling from IDENTITY and the source photos.",
        "",
        SECTION_IDENTITY,
        "Photographer constraints only. Never typeset this object. Use it with the "
        "attached photos for hang, size, pack, colour, print, and mount.",
        "drop is how far the product hangs. opening is the aperture it is made to "
        "cover. Scale that opening to the product and the source photos — if those "
        "photos show a window-height (or other short) opening that the product only "
        "covers, keep that height. Do not stretch the opening to door or "
        "floor-to-ceiling height so the same product looks full-length.",
        "Keep product geometry from IDENTITY and the attached source photos. "
        "Content and Pattern may restyle room and lighting; they must not change drop, "
        "opening, pack, colour, print, or mount, including opening height vs floor.",
        _identity_block(identity_obj),
        "",
        SECTION_OVERLAY_FACTS,
    ]
    if assigned_facts:
        lines.extend(_overlay_rules_when_facts(assigned_facts))
    else:
        lines.extend(_overlay_rules_when_empty())

    lines.extend(["", SECTION_JSON_DNA])
    dna_block = common_image.format_block(brand_look)
    lines.append(dna_block if dna_block else "{}")
    lines.extend(
        [
            "",
            SECTION_FORBIDDEN,
            "Do not draw a logo. Do not mention canvas ratio or font names.",
            "Do not copy badges, size tags, or feature callouts from the reference photos.",
            "No dual-unit charts, pack dimensions, or conversions from the reference photos.",
            "Do not paint SUBJECT.",
            "Do not enlarge the architectural opening to fit overlay callouts.",
        ]
    )
    return "\n".join(lines)


def plan_selected_slots(
    client: OpenRouterClient,
    ctx: GenerationContext,
    name: AttributeName,
    quantity: int,
    *,
    session_id: str | None = None,
) -> dict[tuple[AttributeName, int], SlotPlan]:
    """Plan exactly ``quantity`` slots for one image attribute track."""
    if quantity < 1:
        raise GalleryPlanError(f"quantity must be >= 1 for {name.value}")

    candidate_slots = _candidate_ci_slots(ctx, name)
    if not candidate_slots:
        raise GalleryPlanError(f"no candidate CI slots for {name.value}")

    card = ctx.product_card
    if not isinstance(card, ProductCard):
        # Job path always sets ctx.product_card once for all tracks. This rebuild
        # is a safety net for a single-track call; it cannot share fact ids across
        # IMAGE and A_PLUS.
        claims = sorted({claim for slot in candidate_slots for claim in _feature_priority(slot)})
        card = build_product_card(client, ctx, claims=claims, session_id=session_id)

    chosen_slots = _select_slots(
        candidate_slots,
        quantity=quantity,
        has_overlay_facts=bool(card.facts),
    )
    allocated = _allocate_slots(
        chosen_slots=chosen_slots,
        card=card,
        client=client,
        session_id=session_id,
    )

    out: dict[tuple[AttributeName, int], SlotPlan] = {}
    for slot_position, item in enumerate(allocated, start=1):
        final_prompt = _slot_prompt(
            slot=item.slot_def,
            assigned_facts=item.assigned_facts,
            brand_look=ctx.compressed_brand_dna or "",
            identity=card.identity,
            category=_subject_category(ctx.category_intelligence),
            name=_subject_name(ctx.product),
            category_path=ctx.category_path,
        )
        out[(name, slot_position)] = SlotPlan(
            name=name,
            slot=slot_position,
            prompt=final_prompt,
            concept=item.concept,
            role=_slot_text_field(item.slot_def, "role") or None,
            kind=_slot_text_field(item.slot_def, "kind") or None,
        )
    return out
