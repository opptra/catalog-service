"""Job creation, SKU generation, and flatfile upload orchestration.

``create_job`` inserts ``job`` + ``job_attribute`` + ``sku_generation_job`` rows for the UI.
``execute_sku_generation_job`` runs generation against a pre-created ``sku_generation_job``,
uploads images to GCS, and persists attribute values.
``create_flatfile_job`` / ``complete_flatfile_job`` handle signed-URL flatfile uploads.
"""

import json
import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from core.clients.gcs import GcsClient
from core.clients.openrouter import OpenRouterClient
from core.clients.workflows import WorkflowsClient
from core.config import settings
from core.exceptions import (
    AttributeNotFoundError,
    BrandNotFoundError,
    CategoryNotFoundError,
    FlatfileUploadIncompleteError,
    FlatfileValidationError,
    InvalidJobAttributesError,
    JobNotFoundError,
    MarketplaceNotFoundError,
    ProductNotFoundError,
    SkuGenerationJobExecutionFailedError,
    SkuGenerationJobNotFoundError,
    SkuNotFoundError,
)
from entities.catalog.attribute_enums import (
    AttributeDataType,
    AttributeName,
    FlatfileJobStatus,
    JobStatus,
    JobType,
    SkuGenerationJobStatus,
    TaskStatus,
)
from entities.catalog.attribute_master import AttributeMaster
from entities.catalog.job import Job
from entities.catalog.job_attribute import JobAttribute
from entities.catalog.sku_generation_job import SkuGenerationJob
from entities.catalog.sku_marketplace_attribute_value import SkuMarketplaceAttributeValue
from entities.catalog.sku_master import SkuMaster
from generation import gallery, images, inputs, text
from generation.context import GenerationContext
from repositories.catalog import attribute_master as attribute_master_repo
from repositories.catalog import brand as brand_repo
from repositories.catalog import category as category_repo
from repositories.catalog import job as job_repo
from repositories.catalog import job_attribute as job_attribute_repo
from repositories.catalog import marketplace as marketplace_repo
from repositories.catalog import sku_generation_job as sku_generation_job_repo
from repositories.catalog import sku_marketplace_attribute_value as attribute_value_repo
from repositories.catalog import sku_master as sku_master_repo
from services import category as category_service
from utils import files
from utils import flatfile as flatfile_utils

logger = logging.getLogger(__name__)

# Cloud Workflows resource id for cloud-workflows/job-pipeline.yaml
_JOB_PIPELINE_WORKFLOW = "job-pipeline"

# Cap concurrent OpenRouter image calls. Slots are independent after planning; text + gallery
# planning stay sequential.
_IMAGE_RENDER_WORKERS = 6

_EXECUTABLE_TASK_STATUSES = frozenset({TaskStatus.PENDING, TaskStatus.FAILED})

RenderFn = Callable[
    [OpenRouterClient, GenerationContext, str, AttributeName, int, str | None],
    images.ImageGeneration,
]


def _task_needs_run(tasks: dict[str, Any], attribute_name: str) -> bool:
    """True when the pre-created task exists and is PENDING or FAILED."""
    return tasks.get(attribute_name) in _EXECUTABLE_TASK_STATUSES


def _persist_tasks(
    session: Session, sku_generation_job: SkuGenerationJob, tasks: dict[str, Any]
) -> None:
    """Commit the current task map immediately so a later failure does not lose progress."""
    sku_generation_job.tasks = dict(tasks)
    sku_generation_job_repo.save(session, sku_generation_job)


def _gcs_image_object_name(
    job_external_id: UUID,
    sku_generation_job_external_id: UUID,
    name: AttributeName,
    slot: int,
    content_type: str,
) -> str:
    extension = files.extension_for_image_content_type(content_type)
    return (
        f"jobs/{job_external_id}/sku_generation_jobs/{sku_generation_job_external_id}/images/"
        f"{name.value}_{slot}{extension}"
    )


def _persist_attribute_value(
    session: Session,
    *,
    sku_generation_job: SkuGenerationJob,
    marketplace_id: int,
    attribute_id: int,
    name: str,
    slot: int,
    value: str,
) -> dict[str, Any]:
    """Insert a new versioned attribute value row; never update in place."""
    latest = attribute_value_repo.get_latest_by_slot(
        session,
        sku_id=sku_generation_job.sku_id,
        marketplace_id=marketplace_id,
        attribute_id=attribute_id,
        slot=slot,
    )
    if latest is None:
        external_id = uuid4()
        version = 1
    else:
        external_id = latest.external_id
        version = latest.version + 1

    row = attribute_value_repo.save(
        session,
        SkuMarketplaceAttributeValue(
            external_id=external_id,
            sku_id=sku_generation_job.sku_id,
            marketplace_id=marketplace_id,
            attribute_id=attribute_id,
            slot=slot,
            version=version,
            value=value,
            sku_generation_job_id=sku_generation_job.id,
        ),
    )
    return {
        "external_id": row.external_id,
        "attribute_id": row.attribute_id,
        "name": name,
        "slot": row.slot,
        "version": row.version,
        "value": row.value,
    }


def create_job(
    session: Session,
    workflows: WorkflowsClient,
    *,
    created_by: UUID,
    sku_ids: Sequence[str],
    brand_external_id: UUID,
    marketplace_external_id: UUID,
    attributes: Sequence[tuple[UUID, int]],
) -> dict[str, Any]:
    """Create a job + job_attribute rows + one sku_generation_job per SKU, then start the pipeline.

    ``sku_ids`` are business string ids (``sku_master.attributes.sku_id``).
    ``attributes`` is ``(attribute_external_id, quantity)`` pairs. Quantity must be 1 when the
    attribute does not allow quantity. Returns identifiers the UI needs to track the job.
    """
    brand = brand_repo.get_by_external_id(session, brand_external_id)
    if brand is None:
        raise BrandNotFoundError(f"brand_external_id={brand_external_id}")

    marketplace = marketplace_repo.get_by_external_id(session, marketplace_external_id)
    if marketplace is None:
        raise MarketplaceNotFoundError(f"marketplace_external_id={marketplace_external_id}")

    if not sku_ids:
        raise SkuNotFoundError("sku_ids must not be empty")
    if len(sku_ids) != len(set(sku_ids)):
        raise InvalidJobAttributesError("Duplicate sku_id in sku_ids")
    if any(not sku_id.strip() for sku_id in sku_ids):
        raise InvalidJobAttributesError("sku_ids must not contain blank values")

    found_skus = list(sku_master_repo.list_live_by_attribute_sku_ids(session, sku_ids))
    sku_by_business_id = {
        str(sku.attributes.get("sku_id")): sku
        for sku in found_skus
        if sku.attributes.get("sku_id") is not None
    }
    missing_skus = [sku_id for sku_id in sku_ids if sku_id not in sku_by_business_id]
    if missing_skus:
        raise SkuNotFoundError(f"Unknown or deleted sku_id(s): {missing_skus}")

    attribute_external_ids = [external_id for external_id, _quantity in attributes]
    if len(attribute_external_ids) != len(set(attribute_external_ids)):
        raise InvalidJobAttributesError("Duplicate attribute_external_id in attributes")

    masters = list(attribute_master_repo.list_by_external_ids(session, attribute_external_ids))
    by_external_id = {master.external_id: master for master in masters}
    missing = [
        str(external_id)
        for external_id in attribute_external_ids
        if external_id not in by_external_id
    ]
    if missing:
        raise AttributeNotFoundError(f"Unknown attribute_external_id(s): {missing}")

    resolved: list[tuple[AttributeMaster, int]] = []
    for external_id, quantity in attributes:
        master = by_external_id[external_id]
        if not master.allows_quantity and quantity != 1:
            raise InvalidJobAttributesError(
                f"attribute_external_id={external_id} ({master.name.value}) does not allow quantity>1"
            )
        resolved.append((master, quantity))

    job = job_repo.save(
        session,
        Job(
            created_by=created_by,
            job_type=JobType.GENERATION.value,
            marketplace_id=marketplace.id,
            category_id=None,
            status=JobStatus.PENDING.value,
        ),
    )

    job_attribute_repo.save_all(
        session,
        [
            JobAttribute(job_id=job.id, attribute_id=master.id, quantity=quantity)
            for master, quantity in resolved
        ],
    )

    tasks = {master.name.value: TaskStatus.PENDING.value for master, _quantity in resolved}
    sku_generation_jobs = sku_generation_job_repo.save_all(
        session,
        [
            SkuGenerationJob(
                job_id=job.id,
                sku_id=sku_by_business_id[sku_id].id,
                status=SkuGenerationJobStatus.PENDING.value,
                tasks=dict(tasks),
            )
            for sku_id in sku_ids
        ],
    )

    execution = workflows.trigger(
        _JOB_PIPELINE_WORKFLOW,
        {
            "job_external_id": str(job.external_id),
            "brand_external_id": str(brand.external_id),
            "sku_generation_job_external_ids": [
                str(sku_generation_job.external_id) for sku_generation_job in sku_generation_jobs
            ],
        },
    )

    pk_to_business_sku_id = {
        sku_by_business_id[sku_id].id: sku_id for sku_id in sku_ids
    }

    return {
        "external_id": job.external_id,
        "status": job.status,
        "marketplace_external_id": marketplace.external_id,
        "sku_ids": list(sku_ids),
        "sku_generation_jobs": [
            {
                "sku_id": pk_to_business_sku_id[sku_generation_job.sku_id],
                "external_id": sku_generation_job.external_id,
            }
            for sku_generation_job in sku_generation_jobs
        ],
        "attribute_external_ids": attribute_external_ids,
        "workflow_execution": execution.name,
    }


def complete_job(session: Session, external_id: UUID) -> dict[str, Any]:
    """Mark a parent job COMPLETED (called by the Cloud Workflow after all SKU jobs succeed)."""
    job = job_repo.get_by_external_id(session, external_id)
    if job is None or job.job_type != JobType.GENERATION.value:
        raise JobNotFoundError(str(external_id))

    job.status = JobStatus.COMPLETED.value
    job_repo.save(session, job)
    return {"external_id": job.external_id, "status": job.status}


def execute_sku_generation_job(
    session: Session,
    client: OpenRouterClient,
    gcs: GcsClient,
    external_id: UUID,
    *,
    brand_external_id: UUID,
) -> dict[str, Any]:
    """Run generation for incomplete SKU generation job tasks; upload images and persist."""
    sku_generation_job = sku_generation_job_repo.get_by_external_id(session, external_id)
    if sku_generation_job is None:
        raise SkuGenerationJobNotFoundError(str(external_id))

    # Overall COMPLETED is authoritative — skip reprocessing even if tasks look pending.
    if sku_generation_job.status == SkuGenerationJobStatus.COMPLETED.value:
        return {
            "external_id": sku_generation_job.external_id,
            "status": sku_generation_job.status,
            "tasks": dict(sku_generation_job.tasks or {}),
            "attributes": [],
        }

    job = job_repo.get_by_id(session, sku_generation_job.job_id)
    if job is None or job.job_type != JobType.GENERATION.value:
        raise JobNotFoundError(f"job_id={sku_generation_job.job_id}")
    if job.marketplace_id is None:
        raise JobNotFoundError(f"job {job.external_id} is missing marketplace_id")

    brand = brand_repo.get_by_external_id(session, brand_external_id)
    if brand is None:
        raise BrandNotFoundError(f"brand_external_id={brand_external_id}")

    sku = sku_master_repo.get_by_id(session, sku_generation_job.sku_id)
    if sku is None or sku.deleted_at is not None:
        raise ProductNotFoundError(f"No live SKU for id={sku_generation_job.sku_id}")

    text_attrs, image_attrs, quantities = _selected_attributes(session, sku_generation_job.job_id)
    ctx = inputs.load_context(
        session,
        gcs,
        sku=sku,
        brand_id=brand.id,
        marketplace_id=job.marketplace_id,
    )
    render_fn = images.resolve_image_model(settings.openrouter_image_model)

    # Pre-created task map — never seeded or extended with new attribute keys here.
    tasks: dict[str, Any] = dict(sku_generation_job.tasks or {})
    persisted: list[dict[str, Any]] = []

    text_persisted = _run_text(
        session, sku_generation_job, job.marketplace_id, client, ctx, text_attrs, tasks
    )
    persisted.extend(text_persisted)

    image_persisted = _run_images(
        session,
        sku_generation_job,
        job,
        gcs,
        client,
        ctx,
        image_attrs,
        quantities,
        tasks,
        render_fn,
    )
    persisted.extend(image_persisted)

    status = _derive_status(tasks)
    sku_generation_job.status = status.value
    _persist_tasks(session, sku_generation_job, tasks)

    summary = {
        "external_id": sku_generation_job.external_id,
        "status": status.value,
        "tasks": tasks,
        "attributes": persisted,
    }
    # Non-COMPLETED must fail the HTTP call so Cloud Workflows stops the pipeline.
    if status != SkuGenerationJobStatus.COMPLETED:
        raise SkuGenerationJobExecutionFailedError(
            f"sku_generation_job {sku_generation_job.external_id} "
            f"finished with status {status.value}"
        )
    return summary


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
    sku_generation_job: SkuGenerationJob,
    marketplace_id: int,
    client: OpenRouterClient,
    ctx: GenerationContext,
    text_attrs: list[AttributeMaster],
    tasks: dict[str, Any],
) -> list[dict[str, Any]]:
    """Generate incomplete text attributes; persist each value then mark tasks COMPLETED."""
    pending = [
        attribute
        for attribute in text_attrs
        if _task_needs_run(tasks, AttributeName(attribute.name).value)
    ]
    if not pending:
        return []

    names = [AttributeName(attribute.name) for attribute in pending]
    try:
        generation = text.generate_attributes(client, ctx, names)
    except Exception:  # noqa: BLE001 — mark failed, let images still run
        for name in names:
            tasks[name.value] = TaskStatus.FAILED
        _persist_tasks(session, sku_generation_job, tasks)
        return []

    persisted: list[dict[str, Any]] = []
    by_name = {AttributeName(attribute.name).value: attribute for attribute in pending}
    for name in names:
        attribute = by_name[name.value]
        raw = generation.values.get(name.value)
        value = "" if raw is None else str(raw)
        persisted.append(
            _persist_attribute_value(
                session,
                sku_generation_job=sku_generation_job,
                marketplace_id=marketplace_id,
                attribute_id=attribute.id,
                name=name.value,
                slot=1,
                value=value,
            )
        )
        tasks[name.value] = TaskStatus.COMPLETED
    _persist_tasks(session, sku_generation_job, tasks)
    return persisted


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


def _aspect_ratio_for(name: AttributeName) -> str:
    """The single fixed aspect ratio for this image type (never AI-chosen)."""
    return _ASPECT_RATIO_BY_TYPE.get(name, _DEFAULT_ASPECT_RATIO)


def _run_images(
    session: Session,
    sku_generation_job: SkuGenerationJob,
    job: Job,
    gcs: GcsClient,
    client: OpenRouterClient,
    ctx: GenerationContext,
    image_attrs: list[AttributeMaster],
    quantities: dict[int, int],
    tasks: dict[str, Any],
    render_fn: RenderFn,
) -> list[dict[str, Any]]:
    """Plan and render incomplete image tasks; upload to GCS and persist gs:// links."""
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
        _persist_tasks(session, sku_generation_job, tasks)
        return []

    expected: dict[AttributeName, int] = {
        AttributeName(attribute.name): quantities.get(attribute.id, 1)
        for attribute in pending_attrs
    }
    attribute_id_by_name = {
        AttributeName(attribute.name): attribute.id for attribute in pending_attrs
    }
    jobs = [(name, slot) for name, quantity in expected.items() for slot in range(1, quantity + 1)]
    remaining = dict(expected)
    successes: dict[AttributeName, int] = dict.fromkeys(expected, 0)
    persisted: list[dict[str, Any]] = []

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
                _aspect_ratio_for(name),
            ): (name, slot)
            for name, slot in jobs
        }
        for future in as_completed(futures):
            name, slot = futures[future]
            try:
                generation = future.result()
                uploaded = gcs.upload_bytes(
                    generation.content,
                    _gcs_image_object_name(
                        job.external_id,
                        sku_generation_job.external_id,
                        name,
                        slot,
                        generation.content_type,
                    ),
                    content_type=generation.content_type,
                )
                persisted.append(
                    _persist_attribute_value(
                        session,
                        sku_generation_job=sku_generation_job,
                        marketplace_id=job.marketplace_id,
                        attribute_id=attribute_id_by_name[name],
                        name=name.value,
                        slot=slot,
                        value=uploaded.gs_uri,
                    )
                )
            except Exception as exc:  # noqa: BLE001 — one failed slot fails the attribute
                logger.exception(
                    "Image render/upload failed for %s slot %s: %s", name.value, slot, exc
                )
            else:
                successes[name] += 1

            remaining[name] -= 1
            if remaining[name] == 0:
                tasks[name.value] = (
                    TaskStatus.COMPLETED if successes[name] == expected[name] else TaskStatus.FAILED
                )
                _persist_tasks(session, sku_generation_job, tasks)

    persisted.sort(key=lambda rec: (rec["name"], rec["slot"]))
    return persisted


def _derive_status(tasks: dict[str, Any]) -> SkuGenerationJobStatus:
    """COMPLETED only when every pre-created task is COMPLETED; otherwise FAILED."""
    if tasks and all(status == TaskStatus.COMPLETED for status in tasks.values()):
        return SkuGenerationJobStatus.COMPLETED
    return SkuGenerationJobStatus.FAILED


# --- Flatfile upload ---------------------------------------------------------


def create_flatfile_job(
    session: Session,
    gcs: GcsClient,
    *,
    created_by: UUID,
    category_external_id: UUID,
    template_filename: str,
    template_content_type: str,
    images: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create a FLATFILE_UPLOAD job and return signed PUT/DELETE URLs."""
    category = category_repo.get_by_external_id(session, category_external_id)
    if category is None:
        raise CategoryNotFoundError(f"Category not found: {category_external_id}")

    safe_template_name = flatfile_utils.safe_template_filename(template_filename)
    normalized_images: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for item in images:
        sku_id = flatfile_utils.safe_sku_id(str(item["sku_id"]))
        filename = flatfile_utils.safe_image_filename(str(item["filename"]))
        content_type = str(item["content_type"]).strip()
        if not content_type:
            raise FlatfileValidationError("image content_type is required")
        object_key = flatfile_utils.product_image_object_key(sku_id, filename)
        if object_key in seen_keys:
            raise FlatfileValidationError(f"Duplicate image path: {object_key}")
        seen_keys.add(object_key)
        normalized_images.append(
            {
                "sku_id": sku_id,
                "filename": filename,
                "content_type": content_type,
                "object_key": object_key,
            }
        )

    job = job_repo.save(
        session,
        Job(
            created_by=created_by,
            job_type=JobType.FLATFILE_UPLOAD.value,
            marketplace_id=None,
            category_id=category.id,
            status=FlatfileJobStatus.UPLOADING.value,
        ),
    )

    template_key = flatfile_utils.template_object_key(job.external_id, safe_template_name)
    manifest = {
        "template_object_key": template_key,
        "template_filename": safe_template_name,
        "template_content_type": template_content_type,
        "images": normalized_images,
    }
    gcs.upload_json(manifest, flatfile_utils.manifest_object_key(job.external_id))

    ttl = flatfile_utils.SIGNED_URL_TTL_SECONDS
    image_puts: list[dict[str, Any]] = []
    for item in normalized_images:
        image_puts.append(
            {
                "object_key": item["object_key"],
                "upload_url": gcs.signed_upload_url(
                    item["object_key"],
                    content_type=item["content_type"],
                    expiration_seconds=ttl,
                ),
                "content_type": item["content_type"],
                "sku_id": item["sku_id"],
                "filename": item["filename"],
            }
        )

    new_keys_by_sku: dict[str, set[str]] = {}
    for item in normalized_images:
        new_keys_by_sku.setdefault(item["sku_id"], set()).add(item["object_key"])

    deletes: list[dict[str, Any]] = []
    for sku_id, new_keys in new_keys_by_sku.items():
        existing = gcs.list_object_names(flatfile_utils.product_image_prefix(sku_id))
        for object_key in existing:
            if object_key in new_keys:
                continue
            deletes.append(
                {
                    "object_key": object_key,
                    "delete_url": gcs.signed_delete_url(
                        object_key,
                        expiration_seconds=ttl,
                    ),
                    "sku_id": sku_id,
                }
            )

    return {
        "external_id": job.external_id,
        "status": job.status,
        "template": {
            "object_key": template_key,
            "upload_url": gcs.signed_upload_url(
                template_key,
                content_type=template_content_type,
                expiration_seconds=ttl,
            ),
            "content_type": template_content_type,
        },
        "images": image_puts,
        "deletes": deletes,
    }


def complete_flatfile_job(
    session: Session,
    gcs: GcsClient,
    external_id: UUID,
) -> dict[str, Any]:
    """Verify uploads, enforce mandatory template fields, update sku_master."""
    job = job_repo.get_by_external_id(session, external_id)
    if job is None or job.job_type != JobType.FLATFILE_UPLOAD.value:
        raise JobNotFoundError(str(external_id))

    if job.status == FlatfileJobStatus.COMPLETED.value:
        return {"external_id": job.external_id, "status": job.status, "sku_ids": []}

    if job.category_id is None:
        raise FlatfileValidationError("Flatfile job is missing category_id")

    job.status = FlatfileJobStatus.PROCESSING.value
    job_repo.save(session, job)

    try:
        manifest = json.loads(
            gcs.download_bytes(flatfile_utils.manifest_object_key(job.external_id))
        )
    except Exception as exc:
        job.status = FlatfileJobStatus.FAILED.value
        job_repo.save(session, job)
        raise FlatfileUploadIncompleteError("Upload manifest is missing") from exc

    template_key = str(manifest["template_object_key"])
    images: list[dict[str, Any]] = list(manifest.get("images") or [])

    missing: list[str] = []
    if not gcs.object_exists(template_key):
        missing.append(template_key)
    for item in images:
        key = str(item["object_key"])
        if not gcs.object_exists(key):
            missing.append(key)
    if missing:
        job.status = FlatfileJobStatus.FAILED.value
        job_repo.save(session, job)
        raise FlatfileUploadIncompleteError(
            f"Missing GCS objects: {', '.join(missing[:10])}" + ("…" if len(missing) > 10 else "")
        )

    category = category_repo.get_by_id(session, job.category_id)
    if category is None:
        job.status = FlatfileJobStatus.FAILED.value
        job_repo.save(session, job)
        raise CategoryNotFoundError(f"category_id={job.category_id}")

    template = category_service.get_category_template(session, category.external_id)
    mandatory_names = [field.name for field in template.fields if field.mandatory]

    try:
        headers, rows = flatfile_utils.parse_template_rows(
            gcs.download_bytes(template_key),
            filename=str(manifest.get("template_filename") or "template.csv"),
        )
        flatfile_utils.validate_mandatory_fields(headers, rows, mandatory_names)
        sku_ids = _apply_flatfile_rows_to_sku_master(
            session,
            rows,
            category_id=category.id,
        )
    except (FlatfileValidationError, SkuNotFoundError) as exc:
        job.status = FlatfileJobStatus.FAILED.value
        job_repo.save(session, job)
        raise exc

    job.status = FlatfileJobStatus.COMPLETED.value
    job_repo.save(session, job)
    return {
        "external_id": job.external_id,
        "status": job.status,
        "sku_ids": sku_ids,
    }


def _apply_flatfile_rows_to_sku_master(
    session: Session,
    rows: list[dict[str, str]],
    *,
    category_id: int,
) -> list[str]:
    """Upsert by string attributes.sku_id: update if found, else insert (one save_all)."""
    to_save: list[SkuMaster] = []
    applied: list[str] = []
    for row in rows:
        sku_id = flatfile_utils.row_get(row, "sku_id")
        if not sku_id:
            raise FlatfileValidationError("Missing sku_id value")

        sku = sku_master_repo.get_live_by_attribute_sku_id(session, sku_id)
        attributes = flatfile_utils.build_sku_attributes(
            row,
            sku_id=sku_id,
            existing_attributes=dict(sku.attributes or {}) if sku is not None else None,
        )

        if sku is None:
            sku = SkuMaster(category_id=category_id, attributes=attributes)
        else:
            sku.attributes = attributes
        to_save.append(sku)
        applied.append(sku_id)

    sku_master_repo.save_all(session, to_save)
    return applied


_SIGNED_URL_TTL_SECONDS = 3600


def _business_sku_id(sku: SkuMaster | None, fallback: str = "") -> str:
    if sku is None:
        return fallback
    raw = (sku.attributes or {}).get("sku_id")
    return str(raw) if raw else fallback


def _display_name(sku: SkuMaster | None, business_sku_id: str) -> str | None:
    if sku is None:
        return business_sku_id or None
    attrs = sku.attributes or {}
    for key in ("title", "name", "product_name"):
        value = attrs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return business_sku_id or None


def get_job_status(
    session: Session,
    external_id: UUID,
    *,
    created_by: UUID,
) -> dict[str, Any]:
    """Lightweight pipeline status for polling — no attribute values or signed URLs."""
    job = job_repo.get_by_external_id(session, external_id)
    if job is None or job.created_by != created_by:
        raise JobNotFoundError(f"Job not found: {external_id}")
    if job.job_type != JobType.GENERATION.value:
        raise JobNotFoundError(f"Generation job not found: {external_id}")

    sku_jobs = list(sku_generation_job_repo.list_by_job_id(session, job.id))
    job_attributes = list(job_attribute_repo.list_by_job_id(session, job.id))
    attribute_ids = [ja.attribute_id for ja in job_attributes]
    masters = {
        master.id: master for master in attribute_master_repo.list_by_ids(session, attribute_ids)
    }

    sku_rows = sku_master_repo.list_by_ids(session, [sj.sku_id for sj in sku_jobs])
    sku_by_id = {sku.id: sku for sku in sku_rows}

    marketplace = (
        marketplace_repo.get_by_id(session, job.marketplace_id)
        if job.marketplace_id is not None
        else None
    )
    category = (
        category_repo.get_by_id(session, job.category_id) if job.category_id is not None else None
    )

    completed = sum(1 for sj in sku_jobs if sj.status == SkuGenerationJobStatus.COMPLETED.value)
    failed = sum(1 for sj in sku_jobs if sj.status == SkuGenerationJobStatus.FAILED.value)
    pending = sum(1 for sj in sku_jobs if sj.status == SkuGenerationJobStatus.PENDING.value)

    expected_attributes: list[dict[str, Any]] = []
    for ja in job_attributes:
        master = masters.get(ja.attribute_id)
        if master is None:
            continue
        group = master.group_label.value if master.group_label is not None else None
        expected_attributes.append(
            {
                "attribute_external_id": master.external_id,
                "name": master.name.value,
                "data_type": master.data_type.value,
                "quantity": ja.quantity,
                "group_label": group,
            }
        )

    sku_generation_jobs: list[dict[str, Any]] = []
    for sj in sku_jobs:
        sku = sku_by_id.get(sj.sku_id)
        business_id = _business_sku_id(sku, fallback=str(sj.sku_id))
        sku_generation_jobs.append(
            {
                "external_id": sj.external_id,
                "sku_id": business_id,
                "display_name": _display_name(sku, business_id),
                "status": sj.status,
                "tasks": dict(sj.tasks or {}),
            }
        )

    return {
        "external_id": job.external_id,
        "status": job.status,
        "started_at": job.created_at,
        "updated_at": job.updated_at,
        "marketplace_external_id": marketplace.external_id if marketplace else None,
        "marketplace_name": marketplace.name if marketplace else None,
        "category_external_id": category.external_id if category else None,
        "category_name": category.name if category else None,
        "sku_count": len(sku_jobs),
        "completed_sku_count": completed,
        "failed_sku_count": failed,
        "pending_sku_count": pending,
        "expected_attributes": expected_attributes,
        "sku_generation_jobs": sku_generation_jobs,
    }


def get_sku_generation_job_content(
    session: Session,
    gcs: GcsClient,
    external_id: UUID,
    *,
    created_by: UUID,
) -> dict[str, Any]:
    """Attribute slots for one SKU generation job. IMAGE values are signed GCS URLs."""
    sku_generation_job = sku_generation_job_repo.get_by_external_id(session, external_id)
    if sku_generation_job is None:
        raise SkuGenerationJobNotFoundError(f"SKU generation job not found: {external_id}")

    job = job_repo.get_by_id(session, sku_generation_job.job_id)
    if job is None or job.created_by != created_by:
        raise JobNotFoundError(f"Job not found for SKU generation job: {external_id}")

    job_attributes = list(job_attribute_repo.list_by_job_id(session, job.id))
    attribute_ids = [ja.attribute_id for ja in job_attributes]
    masters = {
        master.id: master for master in attribute_master_repo.list_by_ids(session, attribute_ids)
    }
    quantity_by_attribute_id = {ja.attribute_id: ja.quantity for ja in job_attributes}

    value_rows = attribute_value_repo.list_latest_by_sku_generation_job_id(
        session, sku_generation_job.id
    )
    values_by_key = {(row.attribute_id, row.slot): row for row in value_rows}

    sku = sku_master_repo.get_by_id(session, sku_generation_job.sku_id)
    business_id = _business_sku_id(sku, fallback=str(sku_generation_job.sku_id))
    marketplace = (
        marketplace_repo.get_by_id(session, job.marketplace_id)
        if job.marketplace_id is not None
        else None
    )

    tasks = dict(sku_generation_job.tasks or {})
    attributes: list[dict[str, Any]] = []

    for ja in job_attributes:
        master = masters.get(ja.attribute_id)
        if master is None:
            continue
        quantity = quantity_by_attribute_id.get(ja.attribute_id, ja.quantity)
        task_status = str(tasks.get(master.name.value, TaskStatus.PENDING.value))
        for slot in range(1, quantity + 1):
            row = values_by_key.get((master.id, slot))
            value: str | None = None
            value_is_signed_url = False
            if row is not None and row.value:
                if master.data_type == AttributeDataType.IMAGE and row.value.startswith("gs://"):
                    value = gcs.signed_url_for_gs_uri(
                        row.value, expiration_seconds=_SIGNED_URL_TTL_SECONDS
                    )
                    value_is_signed_url = True
                else:
                    value = row.value

            attributes.append(
                {
                    "attribute_external_id": master.external_id,
                    "name": master.name.value,
                    "data_type": master.data_type.value,
                    "slot": slot,
                    "quantity": quantity,
                    "task_status": task_status,
                    "value_external_id": row.external_id if row is not None else None,
                    "version": row.version if row is not None else None,
                    "value": value,
                    "value_is_signed_url": value_is_signed_url,
                }
            )

    attributes.sort(key=lambda item: (item["name"], item["slot"]))

    return {
        "external_id": sku_generation_job.external_id,
        "job_external_id": job.external_id,
        "sku_id": business_id,
        "display_name": _display_name(sku, business_id),
        "status": sku_generation_job.status,
        "tasks": tasks,
        "marketplace_external_id": marketplace.external_id if marketplace else None,
        "marketplace_name": marketplace.name if marketplace else None,
        "attributes": attributes,
    }
