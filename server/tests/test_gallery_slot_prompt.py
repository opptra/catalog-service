from pipelines.generation.gallery import AssignedFact, _slot_prompt


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
    assert '"value" is immutable' in prompt
    assert "source_field" in prompt and "semantic context" in prompt
    assert "Thread Count: 120" in prompt or "120 Thread Count" in prompt
    assert "do not have to reproduce source_field verbatim" in prompt
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
    assert "Only the facts JSON may determine the claims and information" in prompt
    assert "Do not invent unsupported specifications" in prompt
    assert "Keep the product's identity from the reference photos" in prompt
    assert "Content and Pattern describe infographic type" not in prompt
    assert "Keep the product appearance from the reference photos as the visual priority" not in prompt


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
    assert "Content and Pattern are the shot" in prompt
