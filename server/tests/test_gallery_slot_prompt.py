from pipelines.generation.gallery import AssignedFact, _fact_board_prompt, _slot_prompt


def test_slot_prompt_fact_rendering_contract() -> None:
    prompt = _slot_prompt(
        slot={
            "role": "Product features and benefits",
            "kind": "infographic",
            "content": (
                "Benefits infographic module: catalog-style callout layout beside this product."
            ),
            "pattern": "This product in frame; clean catalog composition.",
        },
        assigned_facts=[
            AssignedFact(
                claim="opacity",
                source_field="Opacity",
                value="Light-filtering (50-60%)",
            )
        ],
        brand_look="",
    )
    assert "On-image text budget: 1 item(s)" in prompt
    assert "once as overlay chrome" in prompt
    assert "Letters printed on the physical product are identity" in prompt
    assert '"value" is immutable' in prompt
    assert "source_field" in prompt and "attribute name and unit context" in prompt
    assert "Thread Count: 120" in prompt or "120 Thread Count" in prompt
    assert "every unit named in source_field stays on the artwork" in prompt
    assert "do not have to reproduce source_field verbatim" not in prompt
    assert "semantic context" not in prompt
    assert '"7 feet" stays "7 feet"' in prompt
    assert "do not add a converted equivalent" in prompt
    assert '"Width (cm)"' in prompt and '"110 cm"' in prompt
    assert "Do not add extra measurements that are not in this facts JSON" in prompt
    assert '"claim": "opacity"' in prompt
    assert '"source_field": "Opacity"' in prompt
    assert '"value": "Light-filtering (50-60%)"' in prompt


def test_slot_prompt_closer_separates_content_from_facts() -> None:
    prompt = _slot_prompt(
        slot={
            "role": "Fabric texture close-up",
            "kind": "detail",
            "content": "Fabric texture module: tight macro of this listing's cloth.",
            "pattern": "Macro of the cloth.",
        },
        assigned_facts=[
            AssignedFact(claim="fabric name", source_field="Fabric", value="Microfiber")
        ],
        brand_look="",
    )
    assert "Content and Pattern are the shot" in prompt
    assert "leaving the reference room behind" in prompt
    assert "not copy to typeset" in prompt
    assert "never paint any word from Slot, Content, Pattern, or JSON DNA" in prompt
    assert "mute visual marks" in prompt
    assert "Numerals and units on measurement lines count as" in prompt
    assert "no dual-unit charts" in prompt
    assert "Do not copy badges, size tags, or feature callouts" in prompt
    assert "Only the facts JSON may determine overlay claims" in prompt
    assert "on-product print" in prompt
    assert "Empty facts JSON means no overlay chrome" in prompt
    assert "Do not invent unsupported specifications" in prompt
    assert "Keep the product's identity from the reference photos" in prompt
    assert "Content (composition only — not on-image copy):" in prompt
    assert "Content and Pattern describe infographic type" not in prompt
    assert (
        "Keep the product appearance from the reference photos as the visual priority" not in prompt
    )


def test_slot_prompt_no_facts_branch_unchanged() -> None:
    prompt = _slot_prompt(
        slot={
            "role": "Styled room hero",
            "kind": "hero",
            "content": "Main discovery shot. Product-first; no on-image specs.",
            "pattern": "Window with this product installed.",
        },
        assigned_facts=[],
        brand_look="",
    )
    assert "This shot has no on-image facts" in prompt
    assert "Paint no product specs" in prompt
    assert "Keep letters that are physically on the product" in prompt
    assert "Empty facts JSON means no overlay chrome" in prompt
    assert "Empty facts JSON means zero words" not in prompt
    assert "Content and Pattern are the shot" in prompt
    assert "Content (composition only — not on-image copy):" in prompt


def test_fact_board_prompt_keeps_one_unit_system_per_claim() -> None:
    prompt = _fact_board_prompt(
        {"Size": "7 feet", "Width (cm)": "110", "Length (CM)": "210"},
        ["product dimensions"],
    )
    assert "Do not convert units" in prompt
    assert '"7 feet" stays "7 feet"' in prompt
    assert "must share one unit system" in prompt
    assert "omit Size rather than mixing systems" in prompt
    assert "Every value must be a verbatim substring" in prompt
