import json
import re
import uuid
from typing import Any

from core.clients.openrouter import OpenRouterClient
from core.config import settings
from core.exceptions import GenerateError, OpenRouterError
from dto.generate import (
    GeneratedImageResult,
    GeneratedTextResult,
    GenerateJobRequest,
    GenerateJobResponse,
    SkuGenerateResult,
)
from services.generate.assets import save_generated_image, save_json_artifact, stamp_official_logo
from services.generate.briefs import normalize_image_brief
from services.generate.inputs import (
    build_image_reference_urls,
    build_sku_context,
    extract_brand_logo_url,
    get_product,
    load_brand_dna,
    load_channel_rules,
    load_creative_concepts,
    load_image_brief_contract,
    load_image_prompt_contract,
    load_manifest_product_keys,
    load_overlay_visual_intelligence,
    load_text_prompt_contract,
    resolve_creative_angle,
)
from services.generate.prompts import (
    build_image_brief_prompt,
    build_image_model_prompt,
    build_text_prompt,
)

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)
_EM_DASH_RE = re.compile(r"[\u2014\u2013]")


def _strip_em_dashes(text: str) -> str:
    return _EM_DASH_RE.sub("-", text)


def _parse_json_object(raw: str, *, label: str) -> dict[str, Any]:
    cleaned = _JSON_FENCE_RE.sub("", raw.strip()).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise GenerateError(f"{label} did not return valid JSON") from exc
    if not isinstance(data, dict):
        raise GenerateError(f"{label} JSON must be an object")
    return data


def _parse_text_json(raw: str) -> GeneratedTextResult:
    data = _parse_json_object(raw, label="Text generation")

    title = data.get("title")
    bullets = data.get("bullet_points")
    highlights = data.get("item_highlights")
    if not isinstance(title, str) or not title.strip():
        raise GenerateError("Generated text missing title")
    if (
        not isinstance(bullets, list)
        or len(bullets) != 5
        or not all(isinstance(item, str) and item.strip() for item in bullets)
    ):
        raise GenerateError("Generated text must include exactly 5 bullet_points")
    if not isinstance(highlights, list) or not (4 <= len(highlights) <= 6):
        raise GenerateError("Generated text must include 4-6 item_highlights")
    if not all(isinstance(item, str) and item.strip() for item in highlights):
        raise GenerateError("item_highlights must be non-empty strings")

    return GeneratedTextResult(
        title=_strip_em_dashes(title.strip()),
        bullet_points=[_strip_em_dashes(item.strip()) for item in bullets],
        item_highlights=[_strip_em_dashes(item.strip()) for item in highlights],
    )


def _parse_image_brief(
    raw: str,
    *,
    image_type: str,
    variant: int,
    creative_angle_name: str,
    concept_angle: str,
    sku_context: dict[str, Any],
    generated_text: dict[str, Any] | None,
) -> dict[str, Any]:
    brief = _parse_json_object(raw, label="Image brief")
    return normalize_image_brief(
        brief,
        image_type=image_type,
        variant=variant,
        creative_angle_name=creative_angle_name,
        concept_angle=concept_angle,
        sku_context=sku_context,
        generated_text=generated_text,
    )


def _generate_text_for_sku(
    client: OpenRouterClient,
    *,
    brand_dna: str,
    channel_rules: dict[str, Any],
    text_contract: dict[str, Any],
    sku_context: dict[str, Any],
    model: str,
) -> GeneratedTextResult:
    prompt = build_text_prompt(
        brand_dna=brand_dna,
        channel_rules=channel_rules,
        sku_context=sku_context,
        text_contract=text_contract,
    )
    raw = client.generate_text(prompt, model=model, json_object=True)
    return _parse_text_json(raw)


def _generate_images_for_sku(
    client: OpenRouterClient,
    *,
    run_id: str,
    product_key: str,
    brand_dna: str,
    channel_rules: dict[str, Any],
    sku_context: dict[str, Any],
    generated_text: GeneratedTextResult | None,
    image_contract: dict[str, Any],
    brief_contract: dict[str, Any],
    overlay_visual: dict[str, Any],
    creative_concepts: dict[str, Any],
    selected_images: dict[str, int],
    text_model: str,
    image_model: str,
) -> tuple[list[GeneratedImageResult], int]:
    results: list[GeneratedImageResult] = []
    calls = 0
    text_payload = generated_text.model_dump() if generated_text is not None else None
    reference_urls = build_image_reference_urls(
        brand_dna=brand_dna,
        sku_context=sku_context,
    )
    if not reference_urls:
        raise GenerateError(f"SKU {product_key} missing primary_image_url for image generation")

    logo_url = extract_brand_logo_url(brand_dna)

    for image_type, quantity in selected_images.items():
        for variant in range(1, quantity + 1):
            try:
                angle = resolve_creative_angle(
                    creative_concepts,
                    image_type=image_type,
                    variant=variant,
                )
                brief_prompt = build_image_brief_prompt(
                    brand_dna=brand_dna,
                    channel_rules=channel_rules,
                    sku_context=sku_context,
                    generated_text=text_payload,
                    image_type=image_type,
                    variant=variant,
                    image_contract=image_contract,
                    brief_contract=brief_contract,
                    overlay_visual=overlay_visual,
                    creative_concepts=creative_concepts,
                    creative_angle_name=angle["creative_angle_name"],
                    concept_angle=angle["concept_angle"],
                )
                brief_raw = client.generate_text(
                    brief_prompt,
                    model=text_model,
                    reference_image_urls=reference_urls,
                    json_object=True,
                )
                calls += 1
                try:
                    brief = _parse_image_brief(
                        brief_raw,
                        image_type=image_type,
                        variant=variant,
                        creative_angle_name=angle["creative_angle_name"],
                        concept_angle=angle["concept_angle"],
                        sku_context=sku_context,
                        generated_text=text_payload,
                    )
                except GenerateError:
                    save_json_artifact(
                        run_id=run_id,
                        product_key=product_key,
                        stem=f"{image_type}_v{variant}_brief_raw",
                        payload={"raw": brief_raw},
                    )
                    raise
                save_json_artifact(
                    run_id=run_id,
                    product_key=product_key,
                    stem=f"{image_type}_v{variant}_brief",
                    payload=brief,
                )

                image_prompt = build_image_model_prompt(
                    brief,
                    overlay_visual=overlay_visual,
                )
                image = client.generate_image(
                    image_prompt,
                    model=image_model,
                    reference_image_urls=reference_urls,
                )
                calls += 1

                if logo_url:
                    image = stamp_official_logo(image.content, logo_url=logo_url)

                relative_path, url = save_generated_image(
                    run_id=run_id,
                    product_key=product_key,
                    image_type=image_type,
                    variant=variant,
                    image=image,
                )
                results.append(
                    GeneratedImageResult(
                        image_type=image_type,
                        variant=variant,
                        url=url,
                        relative_path=relative_path,
                    )
                )
            except (GenerateError, OpenRouterError, ValueError) as exc:
                save_json_artifact(
                    run_id=run_id,
                    product_key=product_key,
                    stem=f"{image_type}_v{variant}_error",
                    payload={"error": str(exc)},
                )
                continue
    if not results:
        raise GenerateError(f"All image generations failed for {product_key}")
    return results, calls


def run_generate_job(
    client: OpenRouterClient,
    request: GenerateJobRequest,
    *,
    session: Any | None = None,
) -> GenerateJobResponse:
    if not request.generate_text and request.images.total() == 0:
        raise GenerateError("Nothing to generate: enable text and/or select image quantities")

    product_keys = request.product_keys or load_manifest_product_keys()
    brand_dna = load_brand_dna()
    channel_rules = load_channel_rules()
    text_contract = load_text_prompt_contract()
    image_contract = load_image_prompt_contract()
    brief_contract = load_image_brief_contract()
    overlay_visual = load_overlay_visual_intelligence()
    creative_concepts = load_creative_concepts()
    selected_images = request.images.selected()

    text_model = request.text_model or settings.openrouter_text_model
    image_model = request.image_model or settings.openrouter_image_model
    run_id = f"run_{uuid.uuid4().hex[:12]}"

    sku_results: list[SkuGenerateResult] = []
    total_calls = 0
    pim_by_key: dict[str, dict[str, Any]] = {}

    for product_key in product_keys:
        calls = 0
        text_result: GeneratedTextResult | None = None
        images: list[GeneratedImageResult] = []
        try:
            product = get_product(product_key)
            pim_by_key[product_key] = product
            sku_context = build_sku_context(product)

            if request.generate_text:
                text_result = _generate_text_for_sku(
                    client,
                    brand_dna=brand_dna,
                    channel_rules=channel_rules,
                    text_contract=text_contract,
                    sku_context=sku_context,
                    model=text_model,
                )
                calls += 1

            if selected_images:
                images, image_calls = _generate_images_for_sku(
                    client,
                    run_id=run_id,
                    product_key=product_key,
                    brand_dna=brand_dna,
                    channel_rules=channel_rules,
                    sku_context=sku_context,
                    generated_text=text_result,
                    image_contract=image_contract,
                    brief_contract=brief_contract,
                    overlay_visual=overlay_visual,
                    creative_concepts=creative_concepts,
                    selected_images=selected_images,
                    text_model=text_model,
                    image_model=image_model,
                )
                calls += image_calls

            sku_results.append(
                SkuGenerateResult(
                    product_key=product_key,
                    text=text_result,
                    images=images,
                    openrouter_calls=calls,
                )
            )
        except (GenerateError, OpenRouterError, ValueError) as exc:
            sku_results.append(
                SkuGenerateResult(
                    product_key=product_key,
                    text=text_result,
                    images=images,
                    openrouter_calls=calls,
                    error=str(exc),
                )
            )
        total_calls += calls

    failed = sum(1 for item in sku_results if item.error)
    status = "completed" if failed == 0 else ("partial" if failed < len(sku_results) else "failed")

    job_external_id: str | None = None
    if request.persist_to_db and session is not None:
        from services.generate.persist import persist_generate_job

        persisted = persist_generate_job(
            session,
            run_id=run_id,
            status=status,
            sku_results=sku_results,
            selected_images=selected_images,
            generate_text=request.generate_text,
            pim_by_key=pim_by_key,
        )
        if persisted is not None:
            job_external_id = str(persisted)

    return GenerateJobResponse(
        run_id=run_id,
        status=status,
        sku_results=sku_results,
        total_openrouter_calls=total_calls,
        job_external_id=job_external_id,
    )
