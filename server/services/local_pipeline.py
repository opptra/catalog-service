"""DEV_MODE stand-in for Cloud Workflows job-pipeline.

Calls the same ``execute_sku_generation_job`` / ``complete_job`` functions
production uses. No FastAPI imports.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from uuid import UUID

from core.clients.db import DatabaseClient
from core.clients.gcs import GcsClient
from core.clients.local_storage import LocalStorageClient
from core.clients.openrouter import OpenRouterClient
from core.exceptions import SkuGenerationJobExecutionFailedError
from entities.catalog.attribute_enums import SkuGenerationJobStatus
from repositories.catalog import job as job_repo
from repositories.catalog import sku_generation_job as sku_generation_job_repo
from services import job as job_service

logger = logging.getLogger(__name__)

_SKU_WORKERS = 3

StorageClient = GcsClient | LocalStorageClient


def run_local_job_pipeline(
    *,
    catalog_db: DatabaseClient,
    openrouter: OpenRouterClient,
    gcs: StorageClient,
    job_external_id: UUID,
    sku_generation_job_ids: list[UUID],
) -> None:
    """Execute SKU jobs (up to 3 at a time), then complete the parent if all succeeded."""

    def _execute_one(sku_external_id: UUID) -> bool:
        session = catalog_db.session_factory()
        try:
            job_service.execute_sku_generation_job(session, openrouter, gcs, sku_external_id)
            return True
        except SkuGenerationJobExecutionFailedError:
            logger.exception(
                "DEV_MODE SKU execute finished unsuccessful sku_generation_job=%s",
                sku_external_id,
            )
            return False
        except Exception:
            logger.exception("DEV_MODE SKU execute crashed sku_generation_job=%s", sku_external_id)
            return False
        finally:
            session.close()

    ok = True
    workers = min(_SKU_WORKERS, len(sku_generation_job_ids)) or 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_execute_one, sku_id) for sku_id in sku_generation_job_ids]
        for future in as_completed(futures):
            if not future.result():
                ok = False

    if not ok:
        logger.warning(
            "DEV_MODE pipeline skipped parent complete for job=%s (a SKU failed)",
            job_external_id,
        )
        return

    session = catalog_db.session_factory()
    try:
        job = job_repo.get_by_external_id(session, job_external_id)
        if job is None:
            return
        siblings = sku_generation_job_repo.list_by_job_id(session, job.id)
        if siblings and all(
            sibling.status == SkuGenerationJobStatus.COMPLETED.value for sibling in siblings
        ):
            job_service.complete_job(session, job_external_id)
    finally:
        session.close()
