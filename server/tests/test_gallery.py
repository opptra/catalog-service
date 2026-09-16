import pytest

from core.exceptions import GalleryPlanError
from pipelines.generation.gallery import (
    AssignedFact,
    FactValue,
    _allocate_slots,
    _facts_block,
    _facts_for_claims,
    _select_slots,
)


def test_facts_for_claims_caps_values_at_max_callouts() -> None:
    board = {
        "dimensions": [
            FactValue('90"', "Length"),
            FactValue('90"', "Width"),
            FactValue('20"', "Drop"),
        ],
        "fill": [FactValue("Microfiber", "Fill")],
    }
    facts = _facts_for_claims(["dimensions", "fill"], board, limit=2)
    assert [(item.field, item.value) for item in facts] == [
        ("Length", '90"'),
        ("Drop", '20"'),
    ]


def test_facts_for_claims_keeps_shopper_field_separate_from_provenance() -> None:
    board = {
        "breathable / lightweight / all-season": [
            FactValue("All", "Seasons"),
        ],
    }
    facts = _facts_for_claims(
        ["breathable / lightweight / all-season"],
        board,
    )
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


def test_allocate_slots_paint_budget_is_max_callouts() -> None:
    slot = {
        "role": "construction",
        "kind": "detail",
        "order": 1,
        "priority": "core",
        "max_callouts": 2,
        "feature_priority": ["fill", "fabric", "thread count"],
    }
    board = {
        "fill": [FactValue("Microfiber", "Fill"), FactValue("8 oz", "Fill Weight")],
        "fabric": [FactValue("Cotton", "Material")],
        "thread count": [FactValue("210", "Thread Count")],
    }
    allocated = _allocate_slots(chosen_slots=[slot], fact_board=board)
    assert allocated[0].owned_claims == ["fill", "fabric"]
    assert [(item.field, item.value) for item in allocated[0].assigned_facts] == [
        ("Fill", "Microfiber"),
        ("Fill Weight", "8 oz"),
    ]


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
    fact_board = {
        "dimensions": [FactValue("45x80 CM", "Size")],
        "anti-slip": [FactValue("rubber backing", "Material")],
        "multi-purpose": [FactValue("kitchen bathroom", "Usage")],
    }

    selected = _select_slots(candidates, quantity=7, fact_board=fact_board)

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


def test_select_slots_skips_callout_slots_with_no_product_facts() -> None:
    """max_callouts > 0 and zero matching facts → do not render an empty overlay."""
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
    fact_board = {"dimensions": [FactValue("120 cm", "Length")]}

    selected = _select_slots(candidates, quantity=3, fact_board=fact_board)

    assert [slot["role"] for slot in selected] == ["hero", "size chart", "hero"]
    assert [slot["order"] for slot in selected] == [1, 3, 2]


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
        _select_slots(candidates, quantity=2, fact_board={})


def test_select_slots_raises_when_candidates_cannot_cover_quantity() -> None:
    candidates = [_slot(kind="hero", role="hero", order=1)]
    with pytest.raises(GalleryPlanError, match="1/3"):
        _select_slots(candidates, quantity=3, fact_board={})
