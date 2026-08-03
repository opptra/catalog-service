"""SKU job orchestration.

Thin use-case layer: resolve the SKU job, decide which attributes to (re)generate, delegate the
actual generation to ``generation`` (which uses the OpenRouter client), record per-attribute status,
persist job/task status, and write the outputs locally.

The database is used ONLY to read metadata and update job/task status — generated content is never
persisted. ``sku_job.tasks`` stores a minimal ``{attribute_name: STATUS}`` map. Resume is
attribute-level: a ``COMPLETED`` attribute is skipped on re-run; no auto-retry within a run.
Images are planned as one coherent gallery (``generation.gallery``) and rendered per slot.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from core.clients.openrouter import OpenRouterClient
from core.config import settings
from core.exceptions import SkuJobNotFoundError
from entities.catalog.attribute_enums import (
    AttributeDataType,
    AttributeName,
    SkuJobStatus,
    TaskStatus,
)
from entities.catalog.attribute_master import AttributeMaster
from entities.catalog.sku_job import SkuJob
from generation import gallery, images, inputs, text
from generation.context import GenerationContext
from repositories.catalog import attribute_master as attribute_master_repo
from repositories.catalog import job_attribute as job_attribute_repo
from repositories.catalog import sku_job as sku_job_repo
from utils import files

# server/services/job.py -> parents[1] == server/
_OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "output"

RenderFn = Callable[
    [OpenRouterClient, GenerationContext, str, AttributeName, int, Path, str | None],
    images.ImageGeneration,
]
# Which render() to call for a given openrouter_image_provider setting — the same switch also
# names the output subfolder (output/gemini/... vs output/gpt/...), so a run's images and its
# provider are always self-evident from the path alone.
_IMAGE_PROVIDERS: dict[str, RenderFn] = {
    "gemini": images.render,
    "gpt": images.render_gpt,
}


def _resolve_image_provider() -> tuple[str, RenderFn]:
    provider = settings.openrouter_image_provider
    try:
        return provider, _IMAGE_PROVIDERS[provider]
    except KeyError:
        raise ValueError(
            f"Unknown openrouter_image_provider={provider!r}; expected one of "
            f"{sorted(_IMAGE_PROVIDERS)}"
        ) from None


def _next_execution_dir(provider: str) -> Path:
    """A fresh sequentially-numbered folder under output/<provider>/ for this run (1, 2, 3, ...).

    Each run gets its own folder so earlier attempts are never overwritten and stay available for
    comparison; each provider numbers its own runs independently.
    """
    root = files.ensure_dir(_OUTPUT_ROOT / provider)
    existing = [int(p.name) for p in root.iterdir() if p.is_dir() and p.name.isdigit()]
    return files.ensure_dir(root / str(max(existing, default=0) + 1))


def execute_sku_job(
    session: Session,
    client: OpenRouterClient,
    external_id: UUID,
) -> dict[str, Any]:
    """Run the full generation task for one SKU job and return a summary of the run."""
    sku_job = sku_job_repo.get_by_external_id(session, external_id)
    if sku_job is None:
        raise SkuJobNotFoundError(str(external_id))

    text_attrs, image_attrs, quantities = _selected_attributes(session, sku_job.job_id)
    ctx = inputs.load_context(sku_job.sku_id)
    provider, render_fn = _resolve_image_provider()

    tasks: dict[str, Any] = dict(sku_job.tasks or {})
    out_dir = _next_execution_dir(provider)

    text_values, text_prompt = _run_text(client, ctx, text_attrs, tasks)
    image_records = _run_images(
        client, ctx, image_attrs, quantities, out_dir / "images", tasks, render_fn
    )

    status = _derive_status(tasks)
    sku_job.status = status.value
    sku_job.tasks = tasks
    sku_job_repo.save(session, sku_job)

    result_path = _write_result(
        out_dir, sku_job, ctx, status, text_values, text_prompt, image_records, tasks
    )
    return {
        "external_id": sku_job.external_id,
        "status": status.value,
        "tasks": tasks,
        "output_dir": str(out_dir),
        "result_path": str(result_path),
        "image_paths": [rec["path"] for rec in image_records],
    }


def _selected_attributes(
    session: Session, job_id: int
) -> tuple[list[AttributeMaster], list[AttributeMaster], dict[int, int]]:
    """Read the job's selected attributes from job_attribute; split by TEXT vs IMAGE."""
    job_attributes = job_attribute_repo.list_by_job_id(session, job_id)
    quantities = {ja.attribute_id: ja.quantity for ja in job_attributes}
    attributes = attribute_master_repo.list_by_ids(session, list(quantities))
    text_attrs = [a for a in attributes if a.data_type == AttributeDataType.TEXT]
    image_attrs = [a for a in attributes if a.data_type == AttributeDataType.IMAGE]
    return text_attrs, image_attrs, quantities


def _run_text(
    client: OpenRouterClient,
    ctx: GenerationContext,
    text_attrs: list[AttributeMaster],
    tasks: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    """Generate all text attributes in one call; return (values, prompt used) or ({}, None)."""
    if not text_attrs:
        return {}, None

    names = [AttributeName(a.name) for a in text_attrs]
    if all(tasks.get(name.value) == TaskStatus.COMPLETED for name in names):
        return {}, None

    try:
        generation = text.generate_attributes(client, ctx, names)
    except Exception:  # noqa: BLE001 — mark failed, let images still run
        for name in names:
            tasks[name.value] = TaskStatus.FAILED
        return {}, None

    for name in names:
        tasks[name.value] = TaskStatus.COMPLETED
    return generation.values, generation.prompt


# Fixed aspect ratio per image type, decided HERE — never taken from the AI plan. A+ content images
# are wide 16:9 banners; every standard gallery image (hero/infographic/lifestyle) is square 1:1.
# A+ ("A_PLUS") is not a generated image type yet: add it to AttributeName and uncomment its entry
# below to make A+ render 16:9.
_ASPECT_RATIO_BY_TYPE: dict[AttributeName, str] = {
    AttributeName.HERO: "1:1",
    AttributeName.INFOGRAPHIC: "1:1",
    AttributeName.LIFESTYLE: "1:1",
    # AttributeName.A_PLUS: "16:9",
}
_DEFAULT_ASPECT_RATIO = "1:1"


def _aspect_ratio_for(name: AttributeName) -> str:
    """The single fixed aspect ratio for this image type (never AI-chosen)."""
    return _ASPECT_RATIO_BY_TYPE.get(name, _DEFAULT_ASPECT_RATIO)


def _run_images(
    client: OpenRouterClient,
    ctx: GenerationContext,
    image_attrs: list[AttributeMaster],
    quantities: dict[int, int],
    images_dir: Path,
    tasks: dict[str, Any],
    render_fn: RenderFn,
) -> list[dict[str, Any]]:
    """Plan the whole gallery once (for coherence), then render the not-COMPLETED types' slots.

    Planning has no fallback: if it fails or misses a slot, every not-yet-completed type is marked
    FAILED and nothing is rendered this run.
    """
    if not image_attrs:
        return []

    requested = [(AttributeName(a.name), quantities.get(a.id, 1)) for a in image_attrs]
    try:
        slot_plans = gallery.plan(client, ctx, requested)
    except Exception:  # noqa: BLE001 — plan covers everything or nothing; mark it all failed
        for attribute in image_attrs:
            name = AttributeName(attribute.name)
            if tasks.get(name.value) != TaskStatus.COMPLETED:
                tasks[name.value] = TaskStatus.FAILED
        return []

    records: list[dict[str, Any]] = []
    for attribute in image_attrs:
        name = AttributeName(attribute.name)
        if tasks.get(name.value) == TaskStatus.COMPLETED:
            continue

        quantity = quantities.get(attribute.id, 1)
        completed = 0
        for slot in range(1, quantity + 1):
            slot_plan = slot_plans[(name, slot)]
            try:
                generation = render_fn(
                    client, ctx, slot_plan.prompt, name, slot, images_dir, _aspect_ratio_for(name)
                )
            except Exception:  # noqa: BLE001 — one failed slot fails the attribute, keep going
                continue
            completed += 1
            records.append(
                {
                    "name": name.value,
                    "slot": slot,
                    "path": str(generation.path),
                    "prompt": generation.prompt,
                }
            )

        tasks[name.value] = TaskStatus.COMPLETED if completed == quantity else TaskStatus.FAILED

    return records


def _derive_status(tasks: dict[str, Any]) -> SkuJobStatus:
    """COMPLETED when every task status is COMPLETED; FAILED if any task failed."""
    if not tasks:
        return SkuJobStatus.COMPLETED
    if all(status == TaskStatus.COMPLETED for status in tasks.values()):
        return SkuJobStatus.COMPLETED
    return SkuJobStatus.FAILED


def _write_result(
    out_dir: Path,
    sku_job: SkuJob,
    ctx: GenerationContext,
    status: SkuJobStatus,
    text_values: dict[str, Any],
    text_prompt: str | None,
    image_records: list[dict[str, Any]],
    tasks: dict[str, Any],
) -> Path:
    result = {
        "sku_job_external_id": str(sku_job.external_id),
        "sku_id": sku_job.sku_id,
        "status": status.value,
        "product": ctx.product,
        "text_attributes": text_values,
        "text_prompt": text_prompt,
        "images": image_records,
        "tasks": tasks,
    }
    return files.write_json(out_dir / "result.json", result)
