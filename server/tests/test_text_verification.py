from typing import Any, cast

from core.clients.openrouter import OpenRouterClient
from entities.catalog.attribute_enums import AttributeName
from pipelines.generation import verify
from pipelines.generation.tools import TEXT_VERIFICATION_TOOL_NAME
from pipelines.generation.verify_text import (
    format_text_value_for_verification,
    verify_text_attribute,
)


class _FakeClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.prompt: str | None = None
        self.cache_prefix: str | None = None
        self.tool_name: str | None = None

    def call_tool(
        self,
        prompt: str,
        *,
        model: str,
        tool: dict[str, Any],
        cache_prefix: str | None = None,
        image_urls: list[str] | None = None,
        max_tokens: int | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        del model, image_urls, max_tokens, session_id
        self.prompt = prompt
        self.cache_prefix = cache_prefix
        self.tool_name = tool["function"]["name"]
        return self.payload


def test_format_text_value_for_verification_lists_and_keywords() -> None:
    bullets = format_text_value_for_verification(
        AttributeName.BULLET_POINTS,
        ["First bullet", "Second bullet"],
    )
    assert bullets == "- First bullet\n- Second bullet"

    keywords = format_text_value_for_verification(
        AttributeName.BACKEND_KEYWORDS,
        '["parda", "office"]',
    )
    assert keywords == "parda office"


def test_verify_text_attribute_uses_text_verification_tool(monkeypatch: Any) -> None:
    monkeypatch.setattr(verify.settings, "openrouter_verify_model", "openai/gpt-4o")
    client = _FakeClient(
        {
            "claims": 95,
            "reasoning": "Material and size match.",
            "mismatches": [],
        }
    )
    product = {"SKU": "ABC", "Material": "Polyester", "Size": "7 feet"}
    result = verify_text_attribute(
        cast(OpenRouterClient, client),
        attribute_name="TITLE",
        generated_text="Polyester curtain 7 feet",
        product=product,
    )
    assert client.tool_name == TEXT_VERIFICATION_TOOL_NAME
    assert client.cache_prefix is not None
    assert "Polyester" in client.cache_prefix
    assert "GENERATED COPY:" in (client.prompt or "")
    assert "ONE-WAY" in (client.prompt or "")
    assert "ATTRIBUTE:" not in (client.prompt or "")
    assert result.claims == 95
    assert result.identity is None
    assert result.confidence == 95
    assert not result.below_threshold()
    payload = result.to_json()
    assert payload["axes"] == {"identity": None, "claims": 95, "quality": None}


def test_ship_score_text_uses_claims_when_no_identity() -> None:
    result = verify.VerificationResult(
        status=verify.STATUS_OK,
        model="openai/gpt-4o",
        attempt=1,
        confidence=4,
        identity=None,
        claims=95,
    )
    assert result.ship_score() == 95
    assert not result.below_threshold()


def test_text_verification_below_threshold_on_low_claims() -> None:
    result = verify.VerificationResult(
        status=verify.STATUS_OK,
        model="openai/gpt-4o",
        attempt=1,
        claims=72,
        confidence=72,
    )
    assert result.below_threshold()
