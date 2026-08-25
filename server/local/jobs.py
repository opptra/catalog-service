"""In-process stand-in for Cloud Workflows ``trigger()``.

Calls the same ``execute_sku_generation_job`` / ``complete_job`` functions
production uses. No FastAPI imports in the worker.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from uuid import UUID

from core.clients.db import DatabaseClient
from core.clients.workflows import WorkflowExecution
from core.exceptions import SkuGenerationJobExecutionFailedError, WorkflowsError
from entities.catalog.attribute_enums import SkuGenerationJobStatus
from repositories.catalog import job as job_repo
from repositories.catalog import sku_generation_job as sku_generation_job_repo
from services import job as job_service

logger = logging.getLogger(__name__)

_SKU_WORKERS = 3


class LocalJobOrchestrator:
    """Duck-types ``WorkflowsClient.trigger`` so ``create_job`` needs no local branch."""

    def __init__(self, app: Any) -> None:
        self._app = app

    def trigger(
        self,
        workflow: str,
        payload: dict[str, Any] | list[Any] | None = None,
    ) -> WorkflowExecution:
        if not workflow:
            raise ValueError("workflow is required")
        if not isinstance(payload, dict):
            raise WorkflowsError("Local job trigger requires a dict payload")

        openrouter = self._app.state.openrouter
        gcs = self._app.state.gcs
        if openrouter is None or gcs is None:
            raise WorkflowsError("OpenRouter or storage is not configured")

        try:
            job_external_id = UUID(str(payload["job_external_id"]))
            sku_ids = [
                UUID(str(item)) for item in payload["sku_generation_job_external_ids"]
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkflowsError(f"Invalid local job payload: {exc}") from exc

        thread = threading.Thread(
            target=_run_local_job_pipeline,
            kwargs={
                "catalog_db": self._app.state.catalog_db,
                "openrouter": openrouter,
                "gcs": gcs,
                "job_external_id": job_external_id,
                "sku_generation_job_ids": sku_ids,
            },
            daemon=True,
            name=f"local-job-{job_external_id}",
        )
        thread.start()
        return WorkflowExecution(name=f"local/{job_external_id}", workflow=workflow)


def _run_local_job_pipeline(
    *,
    catalog_db: DatabaseClient,
    openrouter: Any,
    gcs: Any,
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
                "Local SKU execute finished unsuccessful sku_generation_job=%s",
                sku_external_id,
            )
            return False
        except Exception:
            logger.exception("Local SKU execute crashed sku_generation_job=%s", sku_external_id)
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
            "Local pipeline skipped parent complete for job=%s (a SKU failed)",
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
