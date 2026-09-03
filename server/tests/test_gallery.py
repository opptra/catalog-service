from pipelines.generation.gallery import FactValue, _allocate_slots, _facts_for_claims


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
    assert [(item.source_field, item.value) for item in facts] == [
        ("Length", '90"'),
        ("Drop", '20"'),
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
    board = {
        "fill": [FactValue("Microfiber", "Fill"), FactValue("8 oz", "Fill Weight")],
        "fabric": [FactValue("Cotton", "Material")],
        "thread count": [FactValue("210", "Thread Count")],
    }
    allocated = _allocate_slots(chosen_slots=[slot], fact_board=board)
    assert allocated[0].owned_claims == ["fill", "fabric"]
    assert [(item.source_field, item.value) for item in allocated[0].assigned_facts] == [
        ("Fill", "Microfiber"),
        ("Fill Weight", "8 oz"),
    ]
