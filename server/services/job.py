"""SKU job orchestration.

Thin use-case layer: resolve the SKU job, consume its pre-created task entries, delegate generation
to ``generation`` (which uses the OpenRouter client), update per-task status, persist job/task
status, and write the outputs locally.

The database is used ONLY to read metadata and update job/task status — generated content is never
persisted. ``sku_job.tasks`` is assumed to already contain every task as
``{attribute_name: STATUS}`` (default ``PENDING``). This runner never creates or initializes tasks;
it only executes entries that are ``PENDING`` or ``FAILED`` and leaves ``COMPLETED`` tasks untouched.

Task status is written to the DB the moment an attribute finishes (text batch after its one call;
each image type as soon as all of its slots succeed or fail). Later attributes do not need to
finish before earlier ones become COMPLETED — that is what makes retry skip already-done work.
Images are planned once (``generation.gallery``), then every slot is rendered in parallel.
"""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

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

# Per-run folders: output_latest/<gemini|gpt|grok>/<n>/ — never overwrite a prior run.
# Legacy numbered folders under output/ (output/1, …) stay untouched if present.
_OUTPUT_LATEST = Path(__file__).resolve().parents[1] / "output_latest"

# Cap concurrent OpenRouter image calls. Slots are independent after planning; text + gallery
# planning stay sequential.
_IMAGE_RENDER_WORKERS = 6

_EXECUTABLE_TASK_STATUSES = frozenset({TaskStatus.PENDING, TaskStatus.FAILED})

RenderFn = Callable[
    [OpenRouterClient, GenerationContext, str, AttributeName, int, Path, str | None],
    images.ImageGeneration,
]


def _task_needs_run(tasks: dict[str, Any], attribute_name: str) -> bool:
    """True when the pre-created task exists and is PENDING or FAILED."""
    return tasks.get(attribute_name) in _EXECUTABLE_TASK_STATUSES


def _persist_tasks(session: Session, sku_job: SkuJob, tasks: dict[str, Any]) -> None:
    """Commit the current task map immediately so a later failure does not lose progress."""
    sku_job.tasks = dict(tasks)
    sku_job_repo.save(session, sku_job)


def _next_run_dir(provider: str) -> Path:
    """A fresh numbered folder under output_latest/<provider>/ (1, 2, 3, …)."""
    root = files.ensure_dir(_OUTPUT_LATEST / provider)
    existing = [int(p.name) for p in root.iterdir() if p.is_dir() and p.name.isdigit()]
    return files.ensure_dir(root / str(max(existing, default=0) + 1))


def execute_sku_job(
    session: Session,
    client: OpenRouterClient,
    external_id: UUID,
) -> dict[str, Any]:
    """Run generation for a SKU job's incomplete tasks and return a summary of the run."""
    sku_job = sku_job_repo.get_by_external_id(session, external_id)
    if sku_job is None:
        raise SkuJobNotFoundError(str(external_id))

    text_attrs, image_attrs, quantities = _selected_attributes(session, sku_job.job_id)
    ctx = inputs.load_context(sku_job.sku_id)
    folder, render_fn = images.resolve_image_model(settings.openrouter_image_model)

    # Pre-created task map — never seeded or extended with new attribute keys here.
    tasks: dict[str, Any] = dict(sku_job.tasks or {})
    out_dir = _next_run_dir(folder)

    text_values, text_prompt = _run_text(session, sku_job, client, ctx, text_attrs, tasks)
    image_records = _run_images(
        session,
        sku_job,
        client,
        ctx,
        image_attrs,
        quantities,
        out_dir / "images",
        tasks,
        render_fn,
    )

    status = _derive_status(tasks)
    sku_job.status = status.value
    _persist_tasks(session, sku_job, tasks)

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
    session: Session,
    sku_job: SkuJob,
    client: OpenRouterClient,
    ctx: GenerationContext,
    text_attrs: list[AttributeMaster],
    tasks: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    """Generate incomplete text attributes in one call; return (values, prompt) or ({}, None).

    Text is still one LLM call. After it succeeds, every requested text attribute is marked
    COMPLETED (or all FAILED on error) and that map is persisted immediately so image work
    cannot wipe the text progress.
    """
    names = [
        AttributeName(attribute.name)
        for attribute in text_attrs
        if _task_needs_run(tasks, AttributeName(attribute.name).value)
    ]
    if not names:
        return {}, None

    try:
        generation = text.generate_attributes(client, ctx, names)
    except Exception:  # noqa: BLE001 — mark failed, let images still run
        for name in names:
            tasks[name.value] = TaskStatus.FAILED
        _persist_tasks(session, sku_job, tasks)
        return {}, None

    for name in names:
        tasks[name.value] = TaskStatus.COMPLETED
    _persist_tasks(session, sku_job, tasks)
    return generation.values, generation.prompt


# Fixed aspect ratio per image type, decided HERE — never taken from the AI plan. A+ content
# images are wide banners (Amazon's standard A+ header module is 1464x600, ~21:9 is the closest
# Gemini-supported ratio); every standard gallery image (hero/infographic/lifestyle) is square 1:1.
_ASPECT_RATIO_BY_TYPE: dict[AttributeName, str] = {
    AttributeName.HERO: "1:1",
    AttributeName.INFOGRAPHIC: "1:1",
    AttributeName.LIFESTYLE: "1:1",
    AttributeName.A_PLUS: "21:9",
}
_DEFAULT_ASPECT_RATIO = "1:1"

# A+ content renders into its own images/aplus/ subfolder, separate from the main PDP gallery
# types (hero/infographic/lifestyle) which stay flat in images/ — they belong to a different
# listing surface (the A+ detail-page module vs. the standard image gallery).
_IMAGE_SUBDIR_BY_TYPE: dict[AttributeName, str] = {
    AttributeName.A_PLUS: "aplus",
}


def _images_dir_for(name: AttributeName, images_dir: Path) -> Path:
    """Where this image type's renders are written — a type-specific subfolder if one is mapped,
    else the shared images_dir."""
    subdir = _IMAGE_SUBDIR_BY_TYPE.get(name)
    return images_dir / subdir if subdir else images_dir


def _aspect_ratio_for(name: AttributeName) -> str:
    """The single fixed aspect ratio for this image type (never AI-chosen)."""
    return _ASPECT_RATIO_BY_TYPE.get(name, _DEFAULT_ASPECT_RATIO)


def _run_images(
    session: Session,
    sku_job: SkuJob,
    client: OpenRouterClient,
    ctx: GenerationContext,
    image_attrs: list[AttributeMaster],
    quantities: dict[int, int],
    images_dir: Path,
    tasks: dict[str, Any],
    render_fn: RenderFn,
) -> list[dict[str, Any]]:
    """Plan and render only image tasks that are PENDING or FAILED.

    COMPLETED image tasks are skipped. Planning covers the incomplete types only; if planning fails,
    those incomplete types are marked FAILED and persisted, and nothing is rendered this run.

    After planning, every slot is rendered concurrently (thread pool). Each image type is marked
    COMPLETED/FAILED and committed as soon as all of its own slots finish — hero does not wait
    for A+, etc.
    """
    pending_attrs = [
        attribute
        for attribute in image_attrs
        if _task_needs_run(tasks, AttributeName(attribute.name).value)
    ]
    if not pending_attrs:
        return []

    requested = [
        (AttributeName(attribute.name), quantities.get(attribute.id, 1))
        for attribute in pending_attrs
    ]
    try:
        slot_plans = gallery.plan(client, ctx, requested)
    except Exception:  # noqa: BLE001 — plan covers everything or nothing; mark it all failed
        for attribute in pending_attrs:
            tasks[AttributeName(attribute.name).value] = TaskStatus.FAILED
        _persist_tasks(session, sku_job, tasks)
        return []

    expected: dict[AttributeName, int] = {
        AttributeName(attribute.name): quantities.get(attribute.id, 1)
        for attribute in pending_attrs
    }
    jobs = [
        (name, slot)
        for name, quantity in expected.items()
        for slot in range(1, quantity + 1)
    ]
    remaining = dict(expected)
    successes: dict[AttributeName, int] = dict.fromkeys(expected, 0)
    records: list[dict[str, Any]] = []

    workers = min(_IMAGE_RENDER_WORKERS, len(jobs)) or 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                render_fn,
                client,
                ctx,
                slot_plans[(name, slot)].prompt,
                name,
                slot,
                _images_dir_for(name, images_dir),
                _aspect_ratio_for(name),
            ): (name, slot)
            for name, slot in jobs
        }
        for future in as_completed(futures):
            name, slot = futures[future]
            try:
                generation = future.result()
            except Exception as exc:  # noqa: BLE001 — one failed slot fails the attribute
                logger.exception(
                    "Image render failed for %s slot %s: %s", name.value, slot, exc
                )
            else:
                successes[name] += 1
                records.append(
                    {
                        "name": name.value,
                        "slot": slot,
                        "path": str(generation.path),
                        "prompt": generation.prompt,
                    }
                )

            remaining[name] -= 1
            if remaining[name] == 0:
                tasks[name.value] = (
                    TaskStatus.COMPLETED
                    if successes[name] == expected[name]
                    else TaskStatus.FAILED
                )
                _persist_tasks(session, sku_job, tasks)

    records.sort(key=lambda rec: (rec["name"], rec["slot"]))
    return records


def _derive_status(tasks: dict[str, Any]) -> SkuJobStatus:
    """COMPLETED only when every pre-created task is COMPLETED; otherwise FAILED."""
    if tasks and all(status == TaskStatus.COMPLETED for status in tasks.values()):
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
