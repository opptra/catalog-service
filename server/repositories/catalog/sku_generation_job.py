from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from entities.catalog.sku_generation_job import SkuGenerationJob
from repositories import base


def get_by_id(session: Session, sku_generation_job_id: int) -> SkuGenerationJob | None:
    return session.get(SkuGenerationJob, sku_generation_job_id)


def get_by_external_id(session: Session, external_id: UUID) -> SkuGenerationJob | None:
    return session.scalar(
        select(SkuGenerationJob).where(SkuGenerationJob.external_id == external_id)
    )


def list_by_job_id(session: Session, job_id: int) -> Sequence[SkuGenerationJob]:
    return session.scalars(
        select(SkuGenerationJob)
        .where(SkuGenerationJob.job_id == job_id)
        .order_by(SkuGenerationJob.id.asc())
    ).all()


def list_by_job_ids(
    session: Session, job_ids: Sequence[int]
) -> Sequence[SkuGenerationJob]:
    if not job_ids:
        return []
    return session.scalars(
        select(SkuGenerationJob).where(SkuGenerationJob.job_id.in_(job_ids))
    ).all()


def update_status_if(
    session: Session,
    external_id: UUID,
    *,
    expected_status: str,
    new_status: str,
) -> bool:
    """Atomically flip status when it still matches ``expected_status``.

    Returns True when one row was updated. Commits immediately so concurrent
    callers see the new status before any follow-up work starts.
    """
    result = session.execute(
        update(SkuGenerationJob)
        .where(
            SkuGenerationJob.external_id == external_id,
            SkuGenerationJob.status == expected_status,
        )
        .values(status=new_status, updated_at=func.now())
    )
    session.commit()
    return bool(result.rowcount)


def save(session: Session, sku_generation_job: SkuGenerationJob) -> SkuGenerationJob:
    return base.save(session, sku_generation_job)


def save_all(
    session: Session, sku_generation_jobs: Sequence[SkuGenerationJob]
) -> list[SkuGenerationJob]:
    return base.save_all(session, sku_generation_jobs)
