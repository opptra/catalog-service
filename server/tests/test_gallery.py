import pytest

from core.exceptions import GalleryPlanError
from entities.catalog.attribute_enums import AttributeName
from pipelines.generation.context import GenerationContext
from pipelines.generation.gallery import (
    AssignedFact,
    CardFact,
    IdentityItem,
    ProductCard,
    _allocate_slots,
    _facts_block,
    _facts_for_owned,
    _parse_card_facts,
    _select_slots,
    collect_feature_priority_claims,
    product_card_payload,
)


def test_facts_for_owned_caps_values_at_max_callouts() -> None:
    owned = [
        CardFact("f1", "dimensions", '90"', "Length"),
        CardFact("f2", "dimensions", '90"', "Width"),
        CardFact("f3", "dimensions", '20"', "Drop"),
        CardFact("f4", "fill", "Microfiber", "Fill"),
    ]
    facts = _facts_for_owned(owned, limit=2)
    assert [(item.field, item.value) for item in facts] == [
        ("Length", '90"'),
        ("Drop", '20"'),
    ]


def test_facts_for_owned_keeps_shopper_field_separate_from_provenance() -> None:
    owned = [
        CardFact("f1", "breathable / lightweight / all-season", "All", "Seasons"),
    ]
    facts = _facts_for_owned(owned)
    assert facts[0].field == "Seasons"
    assert facts[0].value == "All"


def test_facts_block_starts_value_with_uppercase() -> None:
    text = _facts_block(
        [
            AssignedFact(claim="softness", field="softness", value="breathable"),
            AssignedFact(
                claim="easy-care",
                field="easy-care",
                value="machine washable",
            ),
            AssignedFact(claim="thread count", field="Thread Count", value="210"),
            AssignedFact(claim="softness", field="softness", value="Super soft"),
        ]
    )
    assert '"value": "Breathable"' in text
    assert '"value": "Machine washable"' in text
    assert '"value": "210"' in text
    assert '"value": "Super soft"' in text
    assert '"value": "breathable"' not in text
    assert '"value": "machine washable"' not in text


def test_facts_block_emits_field_not_source_field() -> None:
    text = _facts_block(
        [
            AssignedFact(
                claim="breathable / lightweight / all-season",
                field="Seasons",
                value="All",
            )
        ]
    )
    assert '"field": "Seasons"' in text
    assert '"value": "All"' in text
    assert "source_field" not in text
    assert "Product Description" not in text


def test_parse_card_facts_drops_restated_normalized_values() -> None:
    facts = _parse_card_facts(
        [
            {"claim": "pack count", "field": "Pack Count", "value": "2"},
            {"claim": "included components", "field": "Included", "value": "2"},
            {"claim": "colour", "field": "Colour", "value": "Grey"},
        ],
        allowed_claims={"pack count", "included components", "colour"},
    )
    assert [(item.field, item.value) for item in facts] == [
        ("Pack Count", "2"),
        ("Colour", "Grey"),
    ]
    assert [item.fact_id for item in facts] == ["f1", "f2"]


def test_product_card_payload_is_qa_shape_without_claim_strings() -> None:
    card = ProductCard(
        identity=(IdentityItem(field="Length", value="63 inches"),),
        facts=(CardFact("f1", "dimensions", "63 inches", "Length"),),
    )
    assert product_card_payload(card) == {
        "identity": [{"field": "Length", "value": "63 inches"}],
        "unique_facts": [{"field": "Length", "value": "63 inches"}],
    }
    assert product_card_payload(None) == {"identity": [], "unique_facts": []}


def test_collect_feature_priority_claims_is_unique_and_sorted() -> None:
    ctx = GenerationContext(
        product={},
        category_intelligence={
            "image_plan": {
                "gallery": {
                    "slots": [
                        {"feature_priority": ["pack count", "dimensions"]},
                        {"feature_priority": ["dimensions"]},
                    ]
                }
            }
        },
        brand_dna="",
    )
    assert collect_feature_priority_claims(ctx, [AttributeName.IMAGE]) == [
        "dimensions",
        "pack count",
    ]


def test_allocate_slots_paint_budget_is_max_callouts() -> None:
    slot = {
        "role": "construction",
        "kind": "detail",
        "order": 1,
        "priority": "core",
        "max_callouts": 2,
        "feature_priority": ["fill", "fabric", "thread count"],
    }
    card = ProductCard(
        identity=(),
        facts=(
            CardFact("f1", "fill", "Microfiber", "Fill"),
            CardFact("f2", "fill", "8 oz", "Fill Weight"),
            CardFact("f3", "fabric", "Cotton", "Material"),
            CardFact("f4", "thread count", "210", "Thread Count"),
        ),
    )
    allocated = _allocate_slots(chosen_slots=[slot], card=card)
    assert allocated[0].owned_claims == ["fill"]
    assert [(item.field, item.value) for item in allocated[0].assigned_facts] == [
        ("Fill", "Microfiber"),
        ("Fill Weight", "8 oz"),
    ]


def test_allocate_slots_fills_unmatched_overlay_from_leftover_facts() -> None:
    slot = {
        "role": "size chart",
        "kind": "infographic",
        "order": 1,
        "priority": "core",
        "max_callouts": 2,
        "feature_priority": ["product dimensions"],
    }
    card = ProductCard(
        identity=(),
        facts=(
            CardFact("f1", "", "63 inches", "Length"),
            CardFact("f2", "", "52 inches", "Width"),
        ),
    )
    allocated = _allocate_slots(chosen_slots=[slot], card=card)
    assert [(item.field, item.value) for item in allocated[0].assigned_facts] == [
        ("Length", "63 inches"),
        ("Width", "52 inches"),
    ]


def test_allocate_slots_applies_tool_then_fifo_for_leftovers() -> None:
    size = {
        "role": "size chart",
        "kind": "infographic",
        "order": 1,
        "priority": "core",
        "max_callouts": 2,
        "feature_priority": ["product dimensions"],
    }
    card = ProductCard(
        identity=(),
        facts=(
            CardFact("f1", "", "63 inches", "Length"),
            CardFact("f2", "", "52 inches", "Width"),
        ),
    )

    class _AssignClient:
        def call_tool(self, *args: object, **kwargs: object) -> dict:
            del args, kwargs
            return {"assignments": [{"fact_id": "f2", "slot_index": 1}]}

    allocated = _allocate_slots(chosen_slots=[size], card=card, client=_AssignClient())
    assert [item.value for item in allocated[0].assigned_facts] == ["52 inches", "63 inches"]


def test_allocate_slots_does_not_reuse_fact_ids_across_slots() -> None:
    hero = {
        "role": "hero",
        "kind": "hero",
        "order": 1,
        "priority": "core",
        "max_callouts": 0,
        "feature_priority": [],
    }
    size = {
        "role": "size chart",
        "kind": "infographic",
        "order": 2,
        "priority": "core",
        "max_callouts": 2,
        "feature_priority": ["dimensions"],
    }
    features = {
        "role": "features",
        "kind": "infographic",
        "order": 3,
        "priority": "core",
        "max_callouts": 2,
        "feature_priority": ["pack count"],
    }
    card = ProductCard(
        identity=(),
        facts=(
            CardFact("f1", "dimensions", "63 inches", "Length"),
            CardFact("f2", "pack count", "2 Panels", "Pack Count"),
        ),
    )
    allocated = _allocate_slots(chosen_slots=[hero, size, features], card=card)
    assert allocated[0].assigned_facts == []
    assert [item.value for item in allocated[1].assigned_facts] == ["63 inches"]
    assert [item.value for item in allocated[2].assigned_facts] == ["2 Panels"]


def _slot(
    *,
    kind: str,
    role: str,
    order: int,
    feature_priority: list[str] | None = None,
    owns: str | None = None,
) -> dict:
    slot: dict = {
        "kind": kind,
        "role": role,
        "order": order,
        "priority": "core",
        "max_callouts": 0,
        "feature_priority": [],
    }
    if feature_priority is not None:
        slot["feature_priority"] = feature_priority
        slot["max_callouts"] = len(feature_priority)
    if owns is not None:
        slot["owns"] = owns
    return slot


def test_select_slots_fills_quantity_when_hero_roles_repeat() -> None:
    """CI often emits several hero variants with the same role and no owns key.

    Unique-role selection then yields 6 slots for a 7-image gallery; the leftover
    hero variant must fill the last slot instead of failing the job.
    """
    candidates = [
        _slot(kind="hero", role="kitchen lifestyle hero", order=1),
        _slot(kind="hero", role="kitchen lifestyle hero", order=2),
        _slot(kind="hero", role="kitchen lifestyle hero", order=3),
        _slot(
            kind="infographic",
            role="size chart",
            order=4,
            feature_priority=["dimensions"],
        ),
        _slot(
            kind="detail",
            role="construction diagram",
            order=5,
            feature_priority=["anti-slip"],
        ),
        _slot(
            kind="infographic",
            role="product features overview",
            order=6,
            feature_priority=["anti-slip"],
        ),
        _slot(
            kind="detail",
            role="anti-slip feature",
            order=7,
            feature_priority=["anti-slip"],
        ),
        _slot(
            kind="lifestyle",
            role="usage scenarios",
            order=8,
            feature_priority=["multi-purpose"],
        ),
    ]

    selected = _select_slots(candidates, quantity=7, has_overlay_facts=True)

    assert [slot["role"] for slot in selected] == [
        "kitchen lifestyle hero",
        "size chart",
        "construction diagram",
        "product features overview",
        "anti-slip feature",
        "usage scenarios",
        "kitchen lifestyle hero",
    ]
    assert selected[0]["order"] == 1
    assert selected[6]["order"] == 2


def test_select_slots_keeps_unmatched_overlay_when_card_has_facts() -> None:
    """Overlay slots stay when the SKU has unique facts — do not fill with an extra hero."""
    candidates = [
        _slot(kind="hero", role="hero", order=1),
        _slot(kind="hero", role="hero", order=2),
        _slot(
            kind="infographic",
            role="size chart",
            order=3,
            feature_priority=["dimensions"],
        ),
        _slot(
            kind="detail",
            role="unsupported overlay",
            order=4,
            feature_priority=["missing claim"],
        ),
    ]

    selected = _select_slots(candidates, quantity=3, has_overlay_facts=True)

    assert [slot["role"] for slot in selected] == ["hero", "size chart", "unsupported overlay"]
    assert [slot["order"] for slot in selected] == [1, 3, 4]


def test_select_slots_skips_callout_slots_when_card_has_no_facts() -> None:
    candidates = [
        _slot(kind="hero", role="hero", order=1),
        _slot(kind="hero", role="hero", order=2),
        _slot(
            kind="infographic",
            role="size chart",
            order=3,
            feature_priority=["dimensions"],
        ),
    ]

    selected = _select_slots(candidates, quantity=2, has_overlay_facts=False)

    assert [slot["role"] for slot in selected] == ["hero", "hero"]
    assert [slot["order"] for slot in selected] == [1, 2]


def test_select_slots_raises_when_only_empty_callout_slots_remain() -> None:
    candidates = [
        _slot(kind="hero", role="hero", order=1),
        _slot(
            kind="infographic",
            role="unsupported overlay",
            order=2,
            feature_priority=["missing claim"],
        ),
    ]
    with pytest.raises(GalleryPlanError, match="1/2"):
        _select_slots(candidates, quantity=2, has_overlay_facts=False)


def test_select_slots_raises_when_candidates_cannot_cover_quantity() -> None:
    candidates = [_slot(kind="hero", role="hero", order=1)]
    with pytest.raises(GalleryPlanError, match="1/3"):
        _select_slots(candidates, quantity=3, has_overlay_facts=True)
