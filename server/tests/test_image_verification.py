from typing import Any, cast

from core.clients.openrouter import OpenRouterClient
from pipelines.generation import verify
from pipelines.generation.tools import IMAGE_VERIFICATION_TOOL_NAME


def test_below_threshold_uses_constant() -> None:
    low = verify.VerificationResult(status=verify.STATUS_OK, model="m", attempt=1, confidence=79)
    edge = verify.VerificationResult(status=verify.STATUS_OK, model="m", attempt=1, confidence=80)
    error = verify.error_result(model="m", attempt=1, error="verify_tool_call_failed")
    assert low.below_threshold()
    assert not edge.below_threshold()
    assert not error.below_threshold()


def test_ok_json_is_the_persisted_snapshot() -> None:
    result = verify.VerificationResult(
        status=verify.STATUS_OK,
        model="openai/gpt-4o",
        attempt=2,
        confidence=61,
        reasoning="Badge reads Queen.",
        observed_text=("Queen", "210"),
        mismatches=(
            verify.VerificationMismatch(
                kind=verify.KIND_CONTRADICTION,
                source_field="Size",
                catalog="King",
                observed="Queen",
            ),
        ),
    )
    payload = result.to_json()
    assert payload == {
        "v": 1,
        "status": "ok",
        "model": "openai/gpt-4o",
        "attempt": 2,
        "confidence": 61,
        "threshold": verify.MIN_CONFIDENCE_PERCENT,
        "reasoning": "Badge reads Queen.",
        "observed_text": ["Queen", "210"],
        "mismatches": [
            {
                "kind": "contradiction",
                "source_field": "Size",
                "catalog": "King",
                "observed": "Queen",
            }
        ],
    }
    assert "expected" not in payload
    assert "visual_match" not in payload


def test_error_json_omits_score() -> None:
    payload = verify.error_result(model="openai/gpt-4o", attempt=1, error="boom").to_json()
    assert payload["status"] == "error"
    assert payload["error"] == "boom"
    assert "confidence" not in payload
    assert "mismatches" not in payload


def test_persist_payload_nests_previous_once() -> None:
    first = verify.VerificationResult(
        status=verify.STATUS_OK,
        model="m",
        attempt=1,
        confidence=40,
        reasoning="Wrong size.",
        mismatches=(
            verify.VerificationMismatch(
                kind=verify.KIND_CONTRADICTION,
                source_field="Size",
                catalog="King",
                observed="Queen",
            ),
        ),
    )
    second = verify.VerificationResult(
        status=verify.STATUS_OK,
        model="m",
        attempt=2,
        confidence=91,
        reasoning="Size now King.",
    )
    payload = verify.persist_payload(second, previous=first)
    assert payload["attempt"] == 2
    assert payload["confidence"] == 91
    assert payload["previous"]["attempt"] == 1
    assert payload["previous"]["confidence"] == 40
    assert payload["previous"]["reasoning"] == "Wrong size."
    assert "previous" not in payload["previous"]


def test_persist_payload_omits_previous_when_absent() -> None:
    result = verify.VerificationResult(
        status=verify.STATUS_OK,
        model="m",
        attempt=1,
        confidence=90,
        reasoning="Clean.",
    )
    payload = verify.persist_payload(result)
    assert "previous" not in payload


def test_retry_addendum_lists_mismatches() -> None:
    result = verify.VerificationResult(
        status=verify.STATUS_OK,
        model="m",
        attempt=1,
        confidence=40,
        reasoning="Wrong size.",
        mismatches=(
            verify.VerificationMismatch(
                kind=verify.KIND_CONTRADICTION,
                source_field="Size",
                catalog="King",
                observed="Queen",
            ),
            verify.VerificationMismatch(
                kind=verify.KIND_INVENTED,
                source_field=None,
                catalog=None,
                observed="FREE SHIPPING",
            ),
        ),
    )
    addendum = verify.retry_addendum(result)
    assert "Size" in addendum
    assert "King" in addendum
    assert "Queen" in addendum
    assert "FREE SHIPPING" in addendum
    assert "source photo" not in addendum.lower()
    assert "reference photo" not in addendum.lower()


class _FakeClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.image_urls: list[str] | None = None
        self.cache_prefix: str | None = None
        self.tool_name: str | None = None

    def call_tool(
        self,
        prompt: str,
        *,
        model: str,
        tool: dict[str, Any],
        image_urls: list[str] | None = None,
        cache_prefix: str | None = None,
        max_tokens: int | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        del prompt, model, max_tokens, session_id
        self.image_urls = image_urls
        self.cache_prefix = cache_prefix
        self.tool_name = tool["function"]["name"]
        return self.payload


def test_verify_image_attaches_only_the_generated_url(monkeypatch: Any) -> None:
    monkeypatch.setattr(verify.settings, "openrouter_verify_model", "openai/gpt-4o")
    client = _FakeClient(
        {
            "confidence": 91,
            "reasoning": "No on-image claims.",
            "observed_text": [],
            "mismatches": [],
        }
    )
    product = {
        "SKU": "ABC",
        "Size": "King",
        "source_assets": ["https://example.com/source.jpg"],
    }
    generated = "https://signed.example/generated.png"
    result = verify.verify_image(
        cast(OpenRouterClient, client),
        generated_image_url=generated,
        product=product,
        attempt=1,
    )
    assert client.image_urls == [generated]
    assert client.tool_name == IMAGE_VERIFICATION_TOOL_NAME
    assert client.cache_prefix is not None
    assert "source_assets" not in client.cache_prefix
    assert "https://example.com/source.jpg" not in client.cache_prefix
    assert result.confidence == 91
    assert not result.below_threshold()


def test_invented_mismatch_clears_catalog_fields() -> None:
    parsed = verify._parse_tool(
        {
            "confidence": 50,
            "reasoning": "Invented slogan.",
            "observed_text": ["FREE SHIPPING"],
            "mismatches": [
                {
                    "kind": "invented",
                    "source_field": "Size",
                    "catalog": "King",
                    "observed": "FREE SHIPPING",
                }
            ],
        },
        model="m",
        attempt=1,
    )
    assert parsed.mismatches[0].kind == "invented"
    assert parsed.mismatches[0].source_field is None
    assert parsed.mismatches[0].catalog is None
    assert parsed.mismatches[0].observed == "FREE SHIPPING"
