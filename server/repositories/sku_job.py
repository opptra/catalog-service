from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.sku_job import SkuJob


def get_by_id(session: Session, sku_job_id: int) -> SkuJob | None:
    return session.get(SkuJob, sku_job_id)


def get_by_external_id(session: Session, external_id: UUID) -> SkuJob | None:
    return session.scalar(select(SkuJob).where(SkuJob.external_id == external_id))
