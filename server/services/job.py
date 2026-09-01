"""Job creation, SKU generation, and flatfile upload orchestration.

``create_job`` inserts ``job`` + ``job_attribute`` + ``sku_generation_job`` rows for the UI.
``execute_sku_generation_job`` runs generation against a pre-created ``sku_generation_job``,
uploads images to GCS, and persists attribute values.
``create_flatfile_job`` / ``complete_flatfile_job`` handle signed-URL flatfile uploads.
"""

import ast
import json
import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from core.clients.gcs import GcsClient
from core.clients.openrouter import OpenRouterClient, attribution_session_id
from core.clients.workflows import WorkflowsClient
from core.config import settings
from core.exceptions import (
    AttributeNotFoundError,
    AttributeValueNotFoundError,
    AttributeValuePromptMissingError,
    AttributeValueRegenerationError,
    BrandNotFoundError,
    CategoryNotFoundError,
    FlatfileUploadIncompleteError,
    FlatfileValidationError,
    GcsError,
    InvalidJobAttributesError,
    JobNotFoundError,
    MarketplaceNotFoundError,
    ProductNotFoundError,
    SkuGenerationJobExecutionFailedError,
    SkuGenerationJobNotFoundError,
    SkuGenerationJobRetryConflictError,
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
from pipelines.generation import (
    common_image,
    gallery,
    images,
    inputs,
    regenerate,
    text,
    tools,
    verify,
    verify_text,
)
from pipelines.generation.context import GenerationContext
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
from services import marketplace_attribute as marketplace_attribute_service
from services import product_attributes as product_attributes_service
from utils import files
from utils import flatfile as flatfile_utils

logger = logging.getLogger(__name__)

# Cloud Workflows resource id — must match the id in cloud-workflows/manifest.yaml.
_JOB_PIPELINE_WORKFLOW = "workflow-1"

# Cap concurrent OpenRouter image calls. Slots are independent after planning; text + gallery
# planning stay sequential.
_IMAGE_RENDER_WORKERS = 6
_SIGNED_URL_TTL_SECONDS = 3600

_EXECUTABLE_TASK_STATUSES = frozenset({TaskStatus.PENDING, TaskStatus.FAILED})

# Legacy Amazon image ratios — used when marketplace_attribute has no image config.
_FALLBACK_ASPECT_RATIO_BY_TYPE: dict[AttributeName, str] = {
    AttributeName.IMAGE: "1:1",
    AttributeName.A_PLUS: "3:2",
}
_DEFAULT_ASPECT_RATIO = "1:1"

RenderFn = Callable[
    [OpenRouterClient, GenerationContext, str, AttributeName, int, str | None, str | None],
    images.ImageGeneration,
]


def _text_limit_for(
    session: Session, marketplace_id: int, attribute_id: int, name: AttributeName
) -> tools.TextLimit | None:
    rules = marketplace_attribute_service.get_rules_for_attribute(
        session, marketplace_id=marketplace_id, attribute_id=attribute_id
    )
    if rules is None:
        return tools.FALLBACK_TEXT_LIMITS.get(name)
    return tools.text_limit_from_config(rules.config) or tools.FALLBACK_TEXT_LIMITS.get(name)


def _aspect_ratio_for_marketplace(
    session: Session, marketplace_id: int, attribute_id: int, name: AttributeName
) -> str:
    """Aspect ratio from marketplace_attribute.config.image, else legacy defaults."""
    rules = marketplace_attribute_service.get_rules_for_attribute(
        session, marketplace_id=marketplace_id, attribute_id=attribute_id
    )
    if rules is not None and rules.aspect_ratio:
        return rules.aspect_ratio
    return _FALLBACK_ASPECT_RATIO_BY_TYPE.get(name, _DEFAULT_ASPECT_RATIO)


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
    prompt: str | None,
    verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert a new versioned attribute value row; never update in place.

    ``external_id`` is deterministic from
    (sku, marketplace, attribute, slot, sku_generation_job). Version bumps use that
    id as the lineage key — never a cross-job slot lookup.
    """
    external_id = attribute_value_repo.lineage_external_id(
        sku_id=sku_generation_job.sku_id,
        marketplace_id=marketplace_id,
        attribute_id=attribute_id,
        slot=slot,
        sku_generation_job_id=sku_generation_job.id,
    )
    latest = attribute_value_repo.get_latest_by_external_id(session, external_id)
    version = 1 if latest is None else latest.version + 1

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
            prompt=prompt,
            verification=verification,
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
        "prompt": row.prompt,
        "verification": row.verification,
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
    job_group_id: UUID | None = None,
) -> dict[str, Any]:
    """Create a job + job_attribute rows + one sku_generation_job per SKU, then start the pipeline.

    ``sku_ids`` are business string ids (``sku_master.attributes.SKU``).
    ``attributes`` is ``(attribute_external_id, quantity)`` pairs. Quantity must be 1 when the
    attribute does not allow quantity. Returns identifiers the UI needs to track the job.
    ``job_group_id`` links sibling marketplace jobs from one wizard submit; generated when omitted.
    """
    brand = brand_repo.get_by_external_id(session, brand_external_id)
    if brand is None:
        raise BrandNotFoundError(f"brand_external_id={brand_external_id}")

    marketplace = marketplace_repo.get_by_external_id(session, marketplace_external_id)
    if marketplace is None or not marketplace.active:
        raise MarketplaceNotFoundError(f"marketplace_external_id={marketplace_external_id}")

    if not sku_ids:
        raise SkuNotFoundError("sku_ids must not be empty")
    if len(sku_ids) != len(set(sku_ids)):
        raise InvalidJobAttributesError("Duplicate sku_id in sku_ids")
    if any(not sku_id.strip() for sku_id in sku_ids):
        raise InvalidJobAttributesError("sku_ids must not contain blank values")

    found_skus = list(sku_master_repo.list_live_by_attribute_sku_ids(session, sku_ids))
    sku_by_business_id: dict[str, SkuMaster] = {}
    for sku in found_skus:
        business_id = product_attributes_service.business_sku_id(sku)
        if business_id:
            sku_by_business_id[business_id] = sku
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

    # Attributes must be offered by this marketplace (when mappings exist).
    marketplace_rules = {
        rule.master.id: rule
        for rule in marketplace_attribute_service.list_rules_for_marketplace(
            session, marketplace.id
        )
    }

    resolved: list[tuple[AttributeMaster, int]] = []
    for external_id, quantity in attributes:
        master = by_external_id[external_id]
        if marketplace_rules and master.id not in marketplace_rules:
            raise InvalidJobAttributesError(
                f"attribute_external_id={external_id} ({master.name.value}) "
                f"is not configured for marketplace {marketplace.name}"
            )
        if not master.allows_quantity and quantity != 1:
            raise InvalidJobAttributesError(
                f"attribute_external_id={external_id} ({master.name.value}) "
                "does not allow quantity>1"
            )
        # Prefer client quantity; if mapping defines image quantity and client sent 1
        # for an allows_quantity attribute, keep client value (wizard sends mapping qty).
        resolved.append((master, quantity))

    # KEY_FEATURES is derived from the job's own DESCRIPTION + BULLET_POINTS output,
    # so those must be generated in the same job.
    selected_names = {AttributeName(master.name) for master, _quantity in resolved}
    if AttributeName.KEY_FEATURES in selected_names:
        missing_sources = [
            source.value
            for source in (AttributeName.BULLET_POINTS, AttributeName.DESCRIPTION)
            if source not in selected_names
        ]
        if missing_sources:
            raise InvalidJobAttributesError(
                f"KEY_FEATURES requires {', '.join(missing_sources)} in the same job"
            )

    group_id = job_group_id if job_group_id is not None else uuid4()

    job = job_repo.save(
        session,
        Job(
            created_by=created_by,
            brand_id=brand.external_id,
            job_type=JobType.GENERATION.value,
            job_group_id=group_id,
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
            "sku_generation_job_external_ids": [
                str(sku_generation_job.external_id) for sku_generation_job in sku_generation_jobs
            ],
        },
    )
    workflow_execution = execution.name

    pk_to_business_sku_id = {sku_by_business_id[sku_id].id: sku_id for sku_id in sku_ids}

    return {
        "external_id": job.external_id,
        "job_group_id": group_id,
        "status": job.status,
        "marketplace_external_id": marketplace.external_id,
        "marketplace_name": marketplace.name,
        "sku_ids": list(sku_ids),
        "sku_generation_jobs": [
            {
                "sku_id": pk_to_business_sku_id[sku_generation_job.sku_id],
                "external_id": sku_generation_job.external_id,
            }
            for sku_generation_job in sku_generation_jobs
        ],
        "attribute_external_ids": attribute_external_ids,
        "workflow_execution": workflow_execution,
    }


def create_jobs_for_marketplaces(
    session: Session,
    workflows: WorkflowsClient,
    *,
    created_by: UUID,
    sku_ids: Sequence[str],
    brand_external_id: UUID,
    marketplaces: Sequence[tuple[UUID, Sequence[tuple[UUID, int]]]],
) -> dict[str, Any]:
    """Create one generation job per marketplace, sharing a single ``job_group_id``.

    ``marketplaces`` is ``(marketplace_external_id, attributes)`` where attributes are
    ``(attribute_external_id, quantity)`` pairs.
    """
    if not marketplaces:
        raise InvalidJobAttributesError("marketplaces must not be empty")
    marketplace_ids = [marketplace_external_id for marketplace_external_id, _ in marketplaces]
    if len(marketplace_ids) != len(set(marketplace_ids)):
        raise InvalidJobAttributesError("Duplicate marketplace_external_id in marketplaces")

    group_id = uuid4()
    jobs: list[dict[str, Any]] = []
    for marketplace_external_id, attributes in marketplaces:
        jobs.append(
            create_job(
                session,
                workflows,
                created_by=created_by,
                sku_ids=sku_ids,
                brand_external_id=brand_external_id,
                marketplace_external_id=marketplace_external_id,
                attributes=attributes,
                job_group_id=group_id,
            )
        )

    return {
        "job_group_id": group_id,
        "jobs": jobs,
        "sku_ids": list(sku_ids),
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
    if job.brand_id is None:
        raise BrandNotFoundError(f"job {job.external_id} is missing brand_id")

    brand = brand_repo.get_by_external_id(session, job.brand_id)
    if brand is None:
        raise BrandNotFoundError(f"brand_external_id={job.brand_id}")

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
    session_id = (
        attribution_session_id(user_external_id=job.created_by, brand_external_id=job.brand_id)
        if job.brand_id is not None
        else None
    )

    return _execute_sku_generation_job_body(
        session,
        sku_generation_job,
        job,
        text_attrs,
        image_attrs,
        quantities,
        client,
        gcs,
        ctx,
        render_fn,
        session_id=session_id,
    )


def _execute_sku_generation_job_body(
    session: Session,
    sku_generation_job: SkuGenerationJob,
    job: Job,
    text_attrs: list[AttributeMaster],
    image_attrs: list[AttributeMaster],
    quantities: dict[int, int],
    client: OpenRouterClient,
    gcs: GcsClient,
    ctx: GenerationContext,
    render_fn: Callable[..., Any],
    *,
    session_id: str | None,
) -> dict[str, Any]:
    # Pre-created task map — never seeded or extended with new attribute keys here.
    tasks: dict[str, Any] = dict(sku_generation_job.tasks or {})
    persisted: list[dict[str, Any]] = []

    text_persisted = _run_text(
        session,
        sku_generation_job,
        job.marketplace_id,
        client,
        ctx,
        text_attrs,
        tasks,
        session_id=session_id,
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
        session_id=session_id,
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


def retry_sku_generation_job(
    session: Session,
    client: OpenRouterClient,
    gcs: GcsClient,
    external_id: UUID,
) -> dict[str, Any]:
    """User-triggered retry: re-run only FAILED tasks of a FAILED SKU job.

    Only a FAILED job is retryable: while the Cloud Workflow is still executing
    the job is PENDING, and retrying then would run two generations against the
    same task map (duplicate renders, conflicting version bumps, last-writer-wins
    task states). The FAILED→PENDING flip is a single conditional UPDATE so two
    concurrent retries cannot both claim the same job.

    The Cloud Workflow that would normally mark the parent job COMPLETED has
    already finished by the time a user retries, so when this retry completes
    the last incomplete sibling, the parent is marked COMPLETED here.
    """
    claimed = sku_generation_job_repo.update_status_if(
        session,
        external_id,
        expected_status=SkuGenerationJobStatus.FAILED.value,
        new_status=SkuGenerationJobStatus.PENDING.value,
    )
    if not claimed:
        sku_generation_job = sku_generation_job_repo.get_by_external_id(session, external_id)
        if sku_generation_job is None:
            raise SkuGenerationJobNotFoundError(str(external_id))
        raise SkuGenerationJobRetryConflictError(
            f"sku_generation_job {external_id} is {sku_generation_job.status}, "
            "only FAILED jobs can be retried"
        )

    summary = execute_sku_generation_job(session, client, gcs, external_id)

    sku_generation_job = sku_generation_job_repo.get_by_external_id(session, external_id)
    if sku_generation_job is not None:
        job = job_repo.get_by_id(session, sku_generation_job.job_id)
        if job is not None and job.status != JobStatus.COMPLETED.value:
            siblings = sku_generation_job_repo.list_by_job_id(session, job.id)
            if all(
                sibling.status == SkuGenerationJobStatus.COMPLETED.value for sibling in siblings
            ):
                job.status = JobStatus.COMPLETED.value
                job_repo.save(session, job)
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


def _serialize_text_value(name: AttributeName, raw: Any) -> str:
    """Storage form of a generated text value: JSON array for list attributes, str otherwise."""
    if name in tools.LIST_TEXT_ATTRIBUTES:
        return json.dumps(raw if isinstance(raw, list) else [], ensure_ascii=False)
    return "" if raw is None else str(raw)


# Visible copy first; backend keywords after title; unknown attrs last.
_TEXT_STAGE_ORDER: tuple[AttributeName, ...] = (
    AttributeName.TITLE,
    AttributeName.ITEM_HIGHLIGHTS,
    AttributeName.BULLET_POINTS,
    AttributeName.DESCRIPTION,
    AttributeName.BACKEND_KEYWORDS,
)


def _text_stage_sort_key(attribute: AttributeMaster) -> tuple[int, str]:
    name = AttributeName(attribute.name)
    try:
        order = _TEXT_STAGE_ORDER.index(name)
    except ValueError:
        order = len(_TEXT_STAGE_ORDER)
    return (order, name.value)


def _run_text(
    session: Session,
    sku_generation_job: SkuGenerationJob,
    marketplace_id: int,
    client: OpenRouterClient,
    ctx: GenerationContext,
    text_attrs: list[AttributeMaster],
    tasks: dict[str, Any],
    *,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """Generate incomplete text attributes; persist value and task status per attr.

    Two stages: every attribute except KEY_FEATURES generates independently first;
    KEY_FEATURES then derives from the completed DESCRIPTION + BULLET_POINTS copy.
    """
    pending = [
        attribute
        for attribute in text_attrs
        if _task_needs_run(tasks, AttributeName(attribute.name).value)
    ]
    if not pending:
        return []

    stage_one = sorted(
        [
            attribute
            for attribute in pending
            if AttributeName(attribute.name) != AttributeName.KEY_FEATURES
        ],
        key=_text_stage_sort_key,
    )
    key_features_attrs = [
        attribute
        for attribute in pending
        if AttributeName(attribute.name) == AttributeName.KEY_FEATURES
    ]

    persisted: list[dict[str, Any]] = []
    raw_values: dict[str, Any] = {}

    for attribute in stage_one:
        name = AttributeName(attribute.name)
        try:
            if name == AttributeName.BACKEND_KEYWORDS:
                generation = text.filter_backend_keywords(
                    client,
                    ctx,
                    session_id=session_id,
                )
            else:
                generation = text.generate_attribute(
                    client,
                    ctx,
                    name,
                    limit=_text_limit_for(session, marketplace_id, attribute.id, name),
                    session_id=session_id,
                )
            raw = generation.values.get(name.value)
            raw_values[name.value] = raw
            text_verification = _safe_verify_text(
                client,
                ctx,
                name=name,
                raw_value=raw,
                session_id=session_id,
            )
            persisted.append(
                _persist_attribute_value(
                    session,
                    sku_generation_job=sku_generation_job,
                    marketplace_id=marketplace_id,
                    attribute_id=attribute.id,
                    name=name.value,
                    slot=1,
                    value=_serialize_text_value(name, raw),
                    prompt=generation.prompt,
                    verification=text_verification,
                )
            )
            tasks[name.value] = TaskStatus.COMPLETED
        except Exception:  # noqa: BLE001 — mark failed, continue other attrs / images
            logger.exception(
                "Text generation failed for %s (sku_generation_job=%s)",
                name.value,
                sku_generation_job.external_id,
            )
            tasks[name.value] = TaskStatus.FAILED
        _persist_tasks(session, sku_generation_job, tasks)

    for attribute in key_features_attrs:
        name = AttributeName.KEY_FEATURES
        try:
            description, bullet_points = _key_features_inputs(
                session, sku_generation_job, text_attrs, tasks, raw_values
            )
            generation = text.generate_key_features(
                client,
                ctx,
                description=description,
                bullet_points=bullet_points,
                limit=_text_limit_for(session, marketplace_id, attribute.id, name),
                session_id=session_id,
            )
            raw = generation.values.get(name.value)
            text_verification = _safe_verify_text(
                client,
                ctx,
                name=name,
                raw_value=raw,
                session_id=session_id,
            )
            persisted.append(
                _persist_attribute_value(
                    session,
                    sku_generation_job=sku_generation_job,
                    marketplace_id=marketplace_id,
                    attribute_id=attribute.id,
                    name=name.value,
                    slot=1,
                    value=_serialize_text_value(name, raw),
                    prompt=generation.prompt,
                    verification=text_verification,
                )
            )
            tasks[name.value] = TaskStatus.COMPLETED
        except Exception:  # noqa: BLE001 — mark failed, continue images
            logger.exception(
                "KEY_FEATURES generation failed (sku_generation_job=%s)",
                sku_generation_job.external_id,
            )
            tasks[name.value] = TaskStatus.FAILED
        _persist_tasks(session, sku_generation_job, tasks)

    return persisted


def _parse_stored_list(value: str) -> list[Any] | None:
    """Parse a stored list value: JSON array, with a fallback for legacy rows
    persisted via ``str(list)`` (Python repr) before JSON serialization existed."""
    try:
        parsed = json.loads(value)
    except ValueError:
        try:
            parsed = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return None
    return parsed if isinstance(parsed, list) else None


def _key_features_inputs(
    session: Session,
    sku_generation_job: SkuGenerationJob,
    text_attrs: list[AttributeMaster],
    tasks: dict[str, Any],
    raw_values: dict[str, Any],
) -> tuple[str, list[str]]:
    """DESCRIPTION text + BULLET_POINTS list feeding the KEY_FEATURES derivation.

    Prefers values generated earlier in this run; falls back to the latest persisted
    rows so a retry that only re-runs KEY_FEATURES still has its inputs. Both source
    tasks must already be COMPLETED.
    """
    for source in (AttributeName.DESCRIPTION, AttributeName.BULLET_POINTS):
        if tasks.get(source.value) != TaskStatus.COMPLETED:
            raise ValueError(f"KEY_FEATURES requires a completed {source.value} task")

    description = raw_values.get(AttributeName.DESCRIPTION.value)
    bullets = raw_values.get(AttributeName.BULLET_POINTS.value)

    if description is None or bullets is None:
        attribute_id_by_name = {
            AttributeName(attribute.name): attribute.id for attribute in text_attrs
        }
        rows = attribute_value_repo.list_latest_by_sku_generation_job_id(
            session, sku_generation_job.id
        )
        row_by_attribute_id = {row.attribute_id: row for row in rows if row.slot == 1}
        if description is None:
            row = row_by_attribute_id.get(attribute_id_by_name.get(AttributeName.DESCRIPTION))
            description = row.value if row is not None else None
        if bullets is None:
            row = row_by_attribute_id.get(attribute_id_by_name.get(AttributeName.BULLET_POINTS))
            bullets = _parse_stored_list(row.value) if row is not None else None

    if not isinstance(description, str) or not description.strip():
        raise ValueError("KEY_FEATURES requires a non-empty DESCRIPTION value")
    if not isinstance(bullets, list) or not bullets:
        raise ValueError("KEY_FEATURES requires a non-empty BULLET_POINTS list")
    return description, [str(bullet) for bullet in bullets]


# Fixed aspect ratio per image type is decided from marketplace_attribute.config —
# never taken from the AI plan. Legacy Amazon defaults live in
# ``_FALLBACK_ASPECT_RATIO_BY_TYPE`` when a mapping row is missing.


@dataclass(frozen=True, slots=True)
class _VerifiedSlotImage:
    gs_uri: str
    prompt: str
    verification: dict[str, Any]


def _safe_verify_image(
    client: OpenRouterClient,
    *,
    generated_image_url: str,
    product: dict[str, Any],
    attempt: int,
    session_id: str | None,
    source_image_urls: list[str] | None = None,
    attribute_name: str | None = None,
    role: str | None = None,
    kind: str | None = None,
) -> verify.VerificationResult:
    """Run verification; never raise — errors become a persisted error snapshot."""
    try:
        return verify.verify_image(
            client,
            generated_image_url=generated_image_url,
            product=product,
            attempt=attempt,
            source_image_urls=source_image_urls,
            attribute_name=attribute_name,
            role=role,
            kind=kind,
            session_id=session_id,
        )
    except Exception:  # noqa: BLE001 — keep the image; do not retry on verifier failure
        logger.exception("Image product-data verification failed (attempt=%s)", attempt)
        return verify.error_result(
            model=settings.openrouter_verify_model,
            attempt=attempt,
            error="verify_tool_call_failed",
        )


def _safe_verify_text(
    client: OpenRouterClient,
    ctx: GenerationContext,
    *,
    name: AttributeName,
    raw_value: Any,
    session_id: str | None,
) -> dict[str, Any]:
    """Run text claims verification; never raise."""
    copy = verify_text.format_text_value_for_verification(name, raw_value)
    if not copy.strip():
        return verify.persist_payload(
            verify.VerificationResult(
                status=verify.STATUS_OK,
                model=settings.openrouter_verify_model,
                attempt=1,
                confidence=100,
                claims=100,
                reasoning="Empty copy — nothing to verify.",
            )
        )
    try:
        result = verify_text.verify_text_attribute(
            client,
            attribute_name=name.value,
            generated_text=copy,
            product=ctx.product,
            session_id=session_id,
        )
    except Exception:  # noqa: BLE001 — keep generated copy
        logger.exception("Text product-data verification failed for %s", name.value)
        result = verify.error_result(
            model=settings.openrouter_verify_model,
            attempt=1,
            error="verify_tool_call_failed",
        )
    return verify.persist_payload(result)


def _slot_context_from_verification(blob: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """role / kind from a prior v2 verification snapshot (user regen has no SlotPlan)."""
    if not isinstance(blob, dict):
        return None, None
    slot = blob.get("slot")
    if not isinstance(slot, dict):
        return None, None
    role = slot.get("role")
    kind = slot.get("kind")
    return (
        str(role).strip() or None if isinstance(role, str) else None,
        str(kind).strip() or None if isinstance(kind, str) else None,
    )


def _render_verify_upload_slot(
    gcs: GcsClient,
    client: OpenRouterClient,
    ctx: GenerationContext,
    render_fn: RenderFn,
    *,
    job_external_id: UUID,
    sku_generation_job_external_id: UUID,
    name: AttributeName,
    slot: int,
    original_prompt: str,
    role: str | None,
    kind: str | None,
    aspect_ratio: str,
    session_id: str | None,
) -> _VerifiedSlotImage:
    """Render, upload, verify; one mismatch retry when enabled, then keep the image."""
    aspect = aspect_ratio

    def _upload(generation: images.ImageGeneration) -> tuple[str, str]:
        uploaded = gcs.upload_bytes(
            generation.content,
            _gcs_image_object_name(
                job_external_id,
                sku_generation_job_external_id,
                name,
                slot,
                generation.content_type,
            ),
            content_type=generation.content_type,
        )
        signed = gcs.signed_url_for_gs_uri(
            uploaded.gs_uri, expiration_seconds=_SIGNED_URL_TTL_SECONDS
        )
        return uploaded.gs_uri, signed

    generation = render_fn(client, ctx, original_prompt, name, slot, aspect, session_id)
    gs_uri, signed = _upload(generation)
    result = _safe_verify_image(
        client,
        generated_image_url=signed,
        product=ctx.product,
        attempt=1,
        session_id=session_id,
        source_image_urls=ctx.product_image_urls,
        attribute_name=name.value,
        role=role,
        kind=kind,
    )
    previous: verify.VerificationResult | None = None
    if verify.should_retry(result):
        first = result
        retry_prompt = f"{original_prompt.strip()}\n\n{verify.retry_addendum(result)}"
        try:
            generation = render_fn(client, ctx, retry_prompt, name, slot, aspect, session_id)
            gs_uri, signed = _upload(generation)
            result = _safe_verify_image(
                client,
                generated_image_url=signed,
                product=ctx.product,
                attempt=2,
                session_id=session_id,
                source_image_urls=ctx.product_image_urls,
                attribute_name=name.value,
                role=role,
                kind=kind,
            )
            previous = first
        except Exception:  # noqa: BLE001 — keep the first image rather than failing the slot
            logger.exception(
                "Image verification retry render failed for %s slot %s; keeping first render",
                name.value,
                slot,
            )
    return _VerifiedSlotImage(
        gs_uri=gs_uri,
        prompt=original_prompt,
        verification=verify.persist_payload(result, previous=previous),
    )


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
    *,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """Plan and render incomplete image tasks; upload to GCS and persist gs:// links."""
    pending_attrs = [
        attribute
        for attribute in image_attrs
        if _task_needs_run(tasks, AttributeName(attribute.name).value)
    ]
    if not pending_attrs:
        return []

    # Compress Brand DNA once into JSON DNA; reuse it on every slot planner prompt.
    ctx = replace(
        ctx,
        compressed_brand_dna=common_image.extract(client, ctx.brand_dna, session_id=session_id),
    )

    # Plan IMAGE and A_PLUS separately — one tool call per attribute type.
    slot_plans: dict[tuple[AttributeName, int], gallery.SlotPlan] = {}
    expected: dict[AttributeName, int] = {}
    attribute_id_by_name: dict[AttributeName, int] = {}
    for attribute in pending_attrs:
        name = AttributeName(attribute.name)
        quantity = quantities.get(attribute.id, 1)
        attribute_id_by_name[name] = attribute.id
        try:
            slot_plans.update(
                gallery.plan_selected_slots(client, ctx, name, quantity, session_id=session_id)
            )
        except Exception:  # noqa: BLE001 — fail this type only; other types still plan/render
            logger.exception("Gallery plan failed for %s", name.value)
            tasks[name.value] = TaskStatus.FAILED
            _persist_tasks(session, sku_generation_job, tasks)
            continue
        expected[name] = quantity

    if not expected:
        return []

    jobs = [(name, slot) for name, quantity in expected.items() for slot in range(1, quantity + 1)]
    remaining = dict(expected)
    successes: dict[AttributeName, int] = dict.fromkeys(expected, 0)
    persisted: list[dict[str, Any]] = []

    workers = min(_IMAGE_RENDER_WORKERS, len(jobs)) or 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _render_verify_upload_slot,
                gcs,
                client,
                ctx,
                render_fn,
                job_external_id=job.external_id,
                sku_generation_job_external_id=sku_generation_job.external_id,
                name=name,
                slot=slot,
                original_prompt=slot_plans[(name, slot)].prompt,
                role=slot_plans[(name, slot)].role,
                kind=slot_plans[(name, slot)].kind,
                aspect_ratio=_aspect_ratio_for_marketplace(
                    session, job.marketplace_id, attribute_id_by_name[name], name
                ),
                session_id=session_id,
            ): (name, slot)
            for name, slot in jobs
        }
        for future in as_completed(futures):
            name, slot = futures[future]
            try:
                rendered = future.result()
                persisted.append(
                    _persist_attribute_value(
                        session,
                        sku_generation_job=sku_generation_job,
                        marketplace_id=job.marketplace_id,
                        attribute_id=attribute_id_by_name[name],
                        name=name.value,
                        slot=slot,
                        value=rendered.gs_uri,
                        prompt=rendered.prompt,
                        verification=rendered.verification,
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
    brand_external_id: UUID,
    category_external_id: UUID,
    template_filename: str,
    template_content_type: str,
    images: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create a FLATFILE_UPLOAD job and return signed PUT/DELETE URLs."""
    brand = brand_repo.get_by_external_id(session, brand_external_id)
    if brand is None:
        raise BrandNotFoundError(f"brand_external_id={brand_external_id}")

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
            brand_id=brand.external_id,
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
    allowed_names = frozenset(field.name for field in template.fields)

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
            allowed_names=allowed_names,
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
    allowed_names: frozenset[str],
) -> list[str]:
    """Upsert by string attributes.SKU: update if found, else insert (one save_all).

    Only category-allowed keys (plus ``SKU``) are written. Extra spreadsheet
    columns and leftover keys from a previous ingest are dropped.
    """
    to_save: list[SkuMaster] = []
    applied: list[str] = []
    for row in rows:
        sku_id = flatfile_utils.row_get(row, "SKU")
        if not sku_id:
            raise FlatfileValidationError("Missing SKU value")

        sku = sku_master_repo.get_live_by_attribute_sku_id(session, sku_id)
        merged = flatfile_utils.build_sku_attributes(
            row,
            sku_id=sku_id,
            existing_attributes=product_attributes_service.merge_base(sku),
        )
        if sku is None:
            sku = SkuMaster(category_id=category_id, attributes={})
        product_attributes_service.apply_write(sku, merged, allowed_names)
        to_save.append(sku)
        applied.append(sku_id)

    sku_master_repo.save_all(session, to_save)
    return applied


def list_jobs(
    session: Session,
    user_session: Session,
    *,
    brand_external_id: UUID,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """List generation executions for a brand, one row per job group (newest first).

    Scoped by ``job.brand_id`` (stores ``brand.external_id``), not by creator.
    Sibling marketplace jobs that share ``job_group_id`` collapse to one row.
    Legacy jobs with NULL ``job_group_id`` appear as their own group keyed by
    ``job.external_id``.
    """
    from repositories.user_service import user as user_repo

    brand = brand_repo.get_by_external_id(session, brand_external_id)
    if brand is None:
        raise BrandNotFoundError(f"brand_external_id={brand_external_id}")

    jobs = list(job_repo.list_generation_by_brand(session, brand.external_id))
    if not jobs:
        return {"items": [], "next_offset": None, "has_more": False}

    sku_jobs = list(sku_generation_job_repo.list_by_job_ids(session, [job.id for job in jobs]))
    sku_jobs_by_job_id: dict[int, list[Any]] = {job.id: [] for job in jobs}
    for sj in sku_jobs:
        bucket = sku_jobs_by_job_id.get(sj.job_id)
        if bucket is not None:
            bucket.append(sj)

    marketplace_ids = {job.marketplace_id for job in jobs if job.marketplace_id is not None}
    marketplaces = {}
    for marketplace_id in marketplace_ids:
        marketplace = marketplace_repo.get_by_id(session, marketplace_id)
        if marketplace is not None:
            marketplaces[marketplace.id] = marketplace

    category_ids = [job.category_id for job in jobs if job.category_id is not None]
    categories = {
        category.id: category
        for category in (
            list(category_repo.list_by_ids(session, list(set(category_ids))))
            if category_ids
            else []
        )
    }

    creator_ids = {job.created_by for job in jobs}
    creators = {
        user.external_id: user
        for user in user_repo.list_by_external_ids(user_session, list(creator_ids))
    }

    # Group jobs: key = job_group_id or external_id for legacy.
    groups: dict[UUID, list[Job]] = {}
    group_order: list[UUID] = []
    for job in jobs:
        key = job.job_group_id if job.job_group_id is not None else job.external_id
        if key not in groups:
            groups[key] = []
            group_order.append(key)
        groups[key].append(job)

    items: list[dict[str, Any]] = []
    for key in group_order:
        members = groups[key]
        marketplace_items: list[dict[str, Any]] = []
        statuses: list[str] = []
        started_at = min(member.created_at for member in members)
        updated_at = max(member.updated_at for member in members)
        category_name: str | None = None
        creator = creators.get(members[0].created_by)
        sku_progress = _unique_sku_progress(
            [sj for member in members for sj in sku_jobs_by_job_id[member.id]]
        )

        for member in members:
            statuses.append(member.status)
            marketplace = (
                marketplaces.get(member.marketplace_id)
                if member.marketplace_id is not None
                else None
            )
            if marketplace is not None:
                marketplace_items.append(
                    {
                        "external_id": marketplace.external_id,
                        "name": marketplace.name,
                        "status": member.status,
                    }
                )
            category = (
                categories.get(member.category_id) if member.category_id is not None else None
            )
            if category is not None and category_name is None:
                category_name = category.name

        items.append(
            {
                "job_group_id": key,
                "external_id": key,
                "status": _rollup_status(statuses),
                "started_at": started_at,
                "updated_at": updated_at,
                "brand_external_id": members[0].brand_id,
                "marketplace_name": ", ".join(item["name"] for item in marketplace_items) or None,
                "marketplaces": marketplace_items,
                "category_name": category_name,
                "created_by_name": creator.name if creator is not None else None,
                "sku_count": sku_progress["total"],
                "completed_sku_count": sku_progress["completed"],
                "failed_sku_count": sku_progress["failed"],
                "pending_sku_count": sku_progress["pending"],
            }
        )

    total_items = len(items)
    for index, item in enumerate(items):
        item["execution_number"] = total_items - index

    paged_items = items[offset : offset + limit]
    next_offset = offset + len(paged_items)
    has_more = next_offset < len(items)

    return {
        "items": paged_items,
        "next_offset": next_offset if has_more else None,
        "has_more": has_more,
    }


def _rollup_status(statuses: Sequence[str]) -> str:
    """pending if any pending; else failed if any failed; else completed."""
    if any(status == JobStatus.PENDING.value for status in statuses):
        return JobStatus.PENDING.value
    if any(status == JobStatus.FAILED.value for status in statuses):
        return JobStatus.FAILED.value
    return JobStatus.COMPLETED.value


def _unique_sku_progress(sku_jobs: Sequence[Any]) -> dict[str, int]:
    """Count unique ``sku_id``s across sibling marketplace jobs.

    A SKU is pending if any marketplace is still pending, failed if none are
    pending and any failed, and completed only when every marketplace completed.
    """
    statuses_by_sku: dict[int, list[str]] = {}
    for sku_job in sku_jobs:
        statuses_by_sku.setdefault(sku_job.sku_id, []).append(sku_job.status)

    completed = 0
    failed = 0
    pending = 0
    for statuses in statuses_by_sku.values():
        rolled = _rollup_status(statuses)
        if rolled == JobStatus.COMPLETED.value:
            completed += 1
        elif rolled == JobStatus.FAILED.value:
            failed += 1
        else:
            pending += 1
    return {
        "total": len(statuses_by_sku),
        "completed": completed,
        "failed": failed,
        "pending": pending,
    }


def get_job_group_status(
    session: Session,
    user_session: Session,
    group_key: UUID,
    *,
    marketplace_external_id: UUID | None = None,
) -> dict[str, Any]:
    """Status for a job group (preview page). Optionally focus one marketplace job.

    SKU counts are unique products across every marketplace in the group.
    ``active_job`` stays the focused marketplace payload for content tabs.
    """
    from repositories.user_service import user as user_repo

    members = list(job_repo.list_group_members(session, group_key))
    if not members:
        raise JobNotFoundError(f"job group not found: {group_key}")

    marketplace_rows: list[dict[str, Any]] = []
    statuses: list[str] = []
    active_job: Job | None = None

    for member in members:
        marketplace = (
            marketplace_repo.get_by_id(session, member.marketplace_id)
            if member.marketplace_id is not None
            else None
        )
        if marketplace is None:
            continue
        statuses.append(member.status)
        marketplace_rows.append(
            {
                "job_external_id": member.external_id,
                "marketplace_external_id": marketplace.external_id,
                "marketplace_name": marketplace.name,
                "status": member.status,
            }
        )
        if marketplace_external_id is not None:
            if marketplace.external_id == marketplace_external_id:
                active_job = member
        elif active_job is None:
            active_job = member

    if active_job is None and members:
        active_job = members[0]

    # Unique SKUs across every marketplace job in the group — not the active tab.
    sku_jobs = list(
        sku_generation_job_repo.list_by_job_ids(session, [member.id for member in members])
    )
    sku_progress = _unique_sku_progress(sku_jobs)

    creator = user_repo.get_by_external_id(user_session, members[0].created_by)
    group_id = (
        members[0].job_group_id if members[0].job_group_id is not None else members[0].external_id
    )

    active_payload = get_job_status(session, active_job.external_id) if active_job else None

    return {
        "job_group_id": group_id,
        "status": _rollup_status(statuses) if statuses else JobStatus.PENDING.value,
        "started_at": min(member.created_at for member in members),
        "updated_at": max(member.updated_at for member in members),
        "brand_external_id": members[0].brand_id,
        "created_by_name": creator.name if creator is not None else None,
        "sku_count": sku_progress["total"],
        "completed_sku_count": sku_progress["completed"],
        "failed_sku_count": sku_progress["failed"],
        "pending_sku_count": sku_progress["pending"],
        "marketplaces": marketplace_rows,
        "active_job": active_payload,
    }


def get_job_status(
    session: Session,
    external_id: UUID,
) -> dict[str, Any]:
    """Lightweight pipeline status for polling — no attribute values or signed URLs."""
    job = job_repo.get_by_external_id(session, external_id)
    if job is None:
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
        config = None
        if job.marketplace_id is not None:
            rules = marketplace_attribute_service.get_rules_for_attribute(
                session,
                marketplace_id=job.marketplace_id,
                attribute_id=master.id,
            )
            if rules is not None:
                config = rules.config.model_dump(exclude_none=True)
        expected_attributes.append(
            {
                "attribute_external_id": master.external_id,
                "name": master.name.value,
                "data_type": master.data_type.value,
                "quantity": ja.quantity,
                "group_label": group,
                "config": config,
            }
        )

    sku_generation_jobs: list[dict[str, Any]] = []
    for sj in sku_jobs:
        sku = sku_by_id.get(sj.sku_id)
        business_id = product_attributes_service.business_sku_id(sku, fallback=str(sj.sku_id))
        sku_generation_jobs.append(
            {
                "external_id": sj.external_id,
                "sku_id": business_id,
                "display_name": product_attributes_service.display_name(sku, business_id),
                "status": sj.status,
                "tasks": dict(sj.tasks or {}),
            }
        )

    return {
        "external_id": job.external_id,
        "job_group_id": job.job_group_id if job.job_group_id is not None else job.external_id,
        "status": job.status,
        "started_at": job.created_at,
        "updated_at": job.updated_at,
        "brand_external_id": job.brand_id,
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
) -> dict[str, Any]:
    """Attribute slots for one SKU generation job. IMAGE values are signed GCS URLs."""
    sku_generation_job = sku_generation_job_repo.get_by_external_id(session, external_id)
    if sku_generation_job is None:
        raise SkuGenerationJobNotFoundError(f"SKU generation job not found: {external_id}")

    job = job_repo.get_by_id(session, sku_generation_job.job_id)
    if job is None:
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
    business_id = product_attributes_service.business_sku_id(
        sku, fallback=str(sku_generation_job.sku_id)
    )
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
                    "prompt": row.prompt if row is not None else None,
                    "verification": row.verification if row is not None else None,
                }
            )

    attributes.sort(key=lambda item: (item["name"], item["slot"]))

    return {
        "external_id": sku_generation_job.external_id,
        "job_external_id": job.external_id,
        "job_group_id": job.job_group_id if job.job_group_id is not None else job.external_id,
        "sku_id": business_id,
        "display_name": product_attributes_service.display_name(sku, business_id),
        "status": sku_generation_job.status,
        "tasks": tasks,
        "marketplace_external_id": marketplace.external_id if marketplace else None,
        "marketplace_name": marketplace.name if marketplace else None,
        "attributes": attributes,
    }


def list_sku_product_images(
    session: Session,
    gcs: GcsClient,
    external_id: UUID,
) -> dict[str, Any]:
    """Signed GET URLs for the SKU's source photos in GCS (flatfile uploads)."""
    sku_generation_job = sku_generation_job_repo.get_by_external_id(session, external_id)
    if sku_generation_job is None:
        raise SkuGenerationJobNotFoundError(f"SKU generation job not found: {external_id}")

    sku = sku_master_repo.get_by_id(session, sku_generation_job.sku_id)
    business_id = product_attributes_service.business_sku_id(sku, fallback="")
    if not business_id:
        raise ProductNotFoundError(f"SKU generation job {external_id} is missing attributes.SKU")

    prefix = flatfile_utils.product_image_prefix(business_id)
    object_names = sorted(gcs.list_object_names(prefix))
    images: list[dict[str, str]] = []
    for object_name in object_names:
        filename = object_name.rsplit("/", 1)[-1]
        if not filename:
            continue
        try:
            url = gcs.signed_url(object_name, expiration_seconds=_SIGNED_URL_TTL_SECONDS)
        except GcsError:
            logger.warning("skip unsigned product image object=%s", object_name)
            continue
        images.append({"filename": filename, "url": url})
    return {"sku_id": business_id, "images": images}


def list_sku_attributes(session: Session, external_id: UUID) -> dict[str, Any]:
    """Filled category-allowed attributes for one SKU — same bag generation sees."""
    sku_generation_job = sku_generation_job_repo.get_by_external_id(session, external_id)
    if sku_generation_job is None:
        raise SkuGenerationJobNotFoundError(f"SKU generation job not found: {external_id}")

    sku = sku_master_repo.get_by_id(session, sku_generation_job.sku_id)
    business_id = product_attributes_service.business_sku_id(sku, fallback="")
    if sku is None or not business_id:
        raise ProductNotFoundError(f"SKU generation job {external_id} is missing attributes.SKU")

    return {
        "sku_id": business_id,
        "attributes": product_attributes_service.present_for_sku(session, sku),
    }


def _origin_brief(session: Session, value_external_id: UUID, latest_prompt: str) -> str:
    """v1 stored prompt is the unique generation brief; later rows are user notes only."""
    origin = attribute_value_repo.get_by_external_id_and_version(session, value_external_id, 1)
    brief = (origin.prompt or "").strip() if origin is not None else ""
    return brief or latest_prompt


def regenerate_attribute_value(
    session: Session,
    client: OpenRouterClient,
    gcs: GcsClient,
    *,
    value_external_id: UUID,
    improvement: str,
) -> dict[str, Any]:
    """Regenerate from v1 brief + current output + this user note; insert a new version.

    Persists only the user note as this version's prompt. Reloads product context;
    does not stack older notes. Keeps the same ``external_id`` and bumps ``version``.
    """
    latest = attribute_value_repo.get_latest_by_external_id(session, value_external_id)
    if latest is None:
        raise AttributeValueNotFoundError(f"attribute value not found: {value_external_id}")

    origin_brief = _origin_brief(session, value_external_id, (latest.prompt or "").strip())
    if not origin_brief:
        raise AttributeValuePromptMissingError(
            f"attribute value {value_external_id} has no stored v1 prompt to regenerate"
        )

    improvement_text = improvement.strip()
    if not improvement_text:
        raise AttributeValueRegenerationError("improvement text is required")

    master = attribute_master_repo.get_by_id(session, latest.attribute_id)
    if master is None:
        raise AttributeNotFoundError(f"attribute_id={latest.attribute_id}")

    sku_generation_job = sku_generation_job_repo.get_by_id(session, latest.sku_generation_job_id)
    if sku_generation_job is None:
        raise SkuGenerationJobNotFoundError(f"sku_generation_job_id={latest.sku_generation_job_id}")

    job = job_repo.get_by_id(session, sku_generation_job.job_id)
    if job is None or job.job_type != JobType.GENERATION.value:
        raise JobNotFoundError(f"job_id={sku_generation_job.job_id}")
    if job.marketplace_id is None:
        raise JobNotFoundError(f"job {job.external_id} is missing marketplace_id")
    if job.brand_id is None:
        raise BrandNotFoundError(f"job {job.external_id} is missing brand_id")

    brand = brand_repo.get_by_external_id(session, job.brand_id)
    if brand is None:
        raise BrandNotFoundError(f"brand_external_id={job.brand_id}")

    sku = sku_master_repo.get_by_id(session, sku_generation_job.sku_id)
    if sku is None or sku.deleted_at is not None:
        raise ProductNotFoundError(f"No live SKU for id={sku_generation_job.sku_id}")

    name = AttributeName(master.name)
    data_type = AttributeDataType(master.data_type)
    ctx = inputs.load_context(
        session,
        gcs,
        sku=sku,
        brand_id=brand.id,
        marketplace_id=job.marketplace_id,
    )
    session_id = (
        attribution_session_id(user_external_id=job.created_by, brand_external_id=job.brand_id)
        if job.brand_id is not None
        else None
    )

    return _regenerate_attribute_value_body(
        session,
        client,
        gcs,
        job=job,
        sku_generation_job=sku_generation_job,
        master=master,
        latest=latest,
        name=name,
        data_type=data_type,
        ctx=ctx,
        origin_brief=origin_brief,
        improvement_text=improvement_text,
        value_external_id=value_external_id,
        session_id=session_id,
    )


def _regenerate_attribute_value_body(
    session: Session,
    client: OpenRouterClient,
    gcs: GcsClient,
    *,
    job: Job,
    sku_generation_job: SkuGenerationJob,
    master: AttributeMaster,
    latest: SkuMarketplaceAttributeValue,
    name: AttributeName,
    data_type: AttributeDataType,
    ctx: GenerationContext,
    origin_brief: str,
    improvement_text: str,
    value_external_id: UUID,
    session_id: str | None,
) -> dict[str, Any]:
    if data_type == AttributeDataType.IMAGE:
        if not latest.value.startswith("gs://"):
            raise AttributeValueRegenerationError(
                f"attribute value {value_external_id} is not a GCS image URI"
            )
        current_image_url = gcs.signed_url_for_gs_uri(
            latest.value, expiration_seconds=_SIGNED_URL_TTL_SECONDS
        )
        try:
            generation = regenerate.regenerate_image(
                client,
                ctx,
                origin_brief=origin_brief,
                improvement=improvement_text,
                aspect_ratio=_aspect_ratio_for_marketplace(
                    session, job.marketplace_id, master.id, name
                ),
                current_image_url=current_image_url,
                session_id=session_id,
            )
            version_key = latest.version + 1

            def _upload_regen(image: images.ImageGeneration) -> tuple[str, str]:
                uploaded = gcs.upload_bytes(
                    image.content,
                    (
                        f"jobs/{job.external_id}/sku_generation_jobs/"
                        f"{sku_generation_job.external_id}/images/"
                        f"{name.value}_{latest.slot}_v{version_key}"
                        f"{files.extension_for_image_content_type(image.content_type)}"
                    ),
                    content_type=image.content_type,
                )
                signed_url = gcs.signed_url_for_gs_uri(
                    uploaded.gs_uri, expiration_seconds=_SIGNED_URL_TTL_SECONDS
                )
                return uploaded.gs_uri, signed_url

            gs_uri, signed = _upload_regen(generation)
            regen_role, regen_kind = _slot_context_from_verification(
                latest.verification if isinstance(latest.verification, dict) else None
            )
            result = _safe_verify_image(
                client,
                generated_image_url=signed,
                product=ctx.product,
                attempt=1,
                session_id=session_id,
                source_image_urls=ctx.product_image_urls,
                attribute_name=name.value,
                role=regen_role,
                kind=regen_kind,
            )
            previous: verify.VerificationResult | None = None
            if verify.should_retry(result):
                first = result
                retry_note = f"{improvement_text}\n\n{verify.retry_addendum(result)}"
                try:
                    generation = regenerate.regenerate_image(
                        client,
                        ctx,
                        origin_brief=origin_brief,
                        improvement=retry_note,
                        aspect_ratio=_aspect_ratio_for_marketplace(
                            session, job.marketplace_id, master.id, name
                        ),
                        current_image_url=signed,
                        session_id=session_id,
                    )
                    gs_uri, signed = _upload_regen(generation)
                    result = _safe_verify_image(
                        client,
                        generated_image_url=signed,
                        product=ctx.product,
                        attempt=2,
                        session_id=session_id,
                        source_image_urls=ctx.product_image_urls,
                        attribute_name=name.value,
                        role=regen_role,
                        kind=regen_kind,
                    )
                    previous = first
                except Exception:  # noqa: BLE001 — keep the first regen
                    logger.exception(
                        "Image regen verification retry failed for %s; keeping first regen",
                        value_external_id,
                    )
            persisted = _persist_attribute_value(
                session,
                sku_generation_job=sku_generation_job,
                marketplace_id=latest.marketplace_id,
                attribute_id=master.id,
                name=name.value,
                slot=latest.slot,
                value=gs_uri,
                prompt=improvement_text,
                verification=verify.persist_payload(result, previous=previous),
            )
            return {
                "value_external_id": persisted["external_id"],
                "attribute_external_id": master.external_id,
                "name": name.value,
                "data_type": data_type.value,
                "slot": latest.slot,
                "version": persisted["version"],
                "value": signed,
                "value_is_signed_url": True,
                "prompt": improvement_text,
                "verification": persisted.get("verification"),
            }
        except AttributeValueRegenerationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AttributeValueRegenerationError(f"image regeneration failed: {exc}") from exc

    try:
        text_result = regenerate.regenerate_text(
            client,
            ctx,
            name=name,
            origin_brief=origin_brief,
            current_value=latest.value,
            improvement=improvement_text,
            limit=_text_limit_for(session, job.marketplace_id, master.id, name),
            session_id=session_id,
        )
        text_verification = _safe_verify_text(
            client,
            ctx,
            name=name,
            raw_value=text_result.value,
            session_id=session_id,
        )
        persisted = _persist_attribute_value(
            session,
            sku_generation_job=sku_generation_job,
            marketplace_id=latest.marketplace_id,
            attribute_id=master.id,
            name=name.value,
            slot=latest.slot,
            value=text_result.value,
            prompt=text_result.prompt,
            verification=text_verification,
        )
        return {
            "value_external_id": persisted["external_id"],
            "attribute_external_id": master.external_id,
            "name": name.value,
            "data_type": data_type.value,
            "slot": latest.slot,
            "version": persisted["version"],
            "value": text_result.value,
            "value_is_signed_url": False,
            "prompt": text_result.prompt,
            "verification": text_verification,
        }
    except AttributeValueRegenerationError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AttributeValueRegenerationError(f"text regeneration failed: {exc}") from exc


def restore_attribute_value_version(
    session: Session,
    gcs: GcsClient,
    *,
    value_external_id: UUID,
    version: int,
) -> dict[str, Any]:
    """Copy an older version forward as a new latest row (same external_id, bumped version)."""
    latest = attribute_value_repo.get_latest_by_external_id(session, value_external_id)
    if latest is None:
        raise AttributeValueNotFoundError(f"attribute value not found: {value_external_id}")

    source = attribute_value_repo.get_by_external_id_and_version(
        session, value_external_id, version
    )
    if source is None:
        raise AttributeValueNotFoundError(
            f"attribute value {value_external_id} version {version} not found"
        )

    master = attribute_master_repo.get_by_id(session, source.attribute_id)
    if master is None:
        raise AttributeNotFoundError(f"attribute_id={source.attribute_id}")

    sku_generation_job = sku_generation_job_repo.get_by_id(session, source.sku_generation_job_id)
    if sku_generation_job is None:
        raise SkuGenerationJobNotFoundError(f"sku_generation_job_id={source.sku_generation_job_id}")

    name = AttributeName(master.name)
    data_type = AttributeDataType(master.data_type)

    if source.version == latest.version:
        value = source.value
        value_is_signed_url = False
        if data_type == AttributeDataType.IMAGE and source.value.startswith("gs://"):
            value = gcs.signed_url_for_gs_uri(
                source.value, expiration_seconds=_SIGNED_URL_TTL_SECONDS
            )
            value_is_signed_url = True
        return {
            "value_external_id": source.external_id,
            "attribute_external_id": master.external_id,
            "name": name.value,
            "data_type": data_type.value,
            "slot": source.slot,
            "version": source.version,
            "value": value,
            "value_is_signed_url": value_is_signed_url,
            "prompt": source.prompt,
            "verification": source.verification,
        }

    persisted = _persist_attribute_value(
        session,
        sku_generation_job=sku_generation_job,
        marketplace_id=source.marketplace_id,
        attribute_id=master.id,
        name=name.value,
        slot=source.slot,
        value=source.value,
        prompt=source.prompt,
        verification=source.verification,
    )

    value = persisted["value"]
    value_is_signed_url = False
    if data_type == AttributeDataType.IMAGE and str(value).startswith("gs://"):
        value = gcs.signed_url_for_gs_uri(str(value), expiration_seconds=_SIGNED_URL_TTL_SECONDS)
        value_is_signed_url = True

    return {
        "value_external_id": persisted["external_id"],
        "attribute_external_id": master.external_id,
        "name": name.value,
        "data_type": data_type.value,
        "slot": source.slot,
        "version": persisted["version"],
        "value": value,
        "value_is_signed_url": value_is_signed_url,
        "prompt": persisted.get("prompt"),
        "verification": persisted.get("verification"),
    }
