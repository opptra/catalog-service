from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.catalog.sku_job import SkuJob
from repositories import base


def get_by_id(session: Session, sku_job_id: int) -> SkuJob | None:
    return session.get(SkuJob, sku_job_id)


def get_by_external_id(session: Session, external_id: UUID) -> SkuJob | None:
    return session.scalar(select(SkuJob).where(SkuJob.external_id == external_id))


def save(session: Session, sku_job: SkuJob) -> SkuJob:
    return base.save(session, sku_job)


def save_all(session: Session, sku_jobs: Sequence[SkuJob]) -> list[SkuJob]:
    return base.save_all(session, sku_jobs)
