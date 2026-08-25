from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.catalog.attribute_enums import JobType
from entities.catalog.job import Job
from repositories import base


def get_by_id(session: Session, job_id: int) -> Job | None:
    return session.get(Job, job_id)


def get_by_external_id(session: Session, external_id: UUID) -> Job | None:
    return session.scalar(select(Job).where(Job.external_id == external_id))


def list_generation_by_brand(session: Session, brand_id: UUID) -> Sequence[Job]:
    """Newest generation jobs first for the given brand.external_id (all creators).

    Soft-deleted jobs (``deleted_at`` set) are excluded from the UI history list.
    """
    return session.scalars(
        select(Job)
        .where(
            Job.brand_id == brand_id,
            Job.job_type == JobType.GENERATION.value,
            Job.deleted_at.is_(None),
        )
        .order_by(Job.created_at.desc())
    ).all()


def list_by_job_group_id(session: Session, job_group_id: UUID) -> Sequence[Job]:
    """All generation jobs in a group. Soft-deleted excluded."""
    return session.scalars(
        select(Job)
        .where(
            Job.job_group_id == job_group_id,
            Job.job_type == JobType.GENERATION.value,
            Job.deleted_at.is_(None),
        )
        .order_by(Job.created_at.asc())
    ).all()


def list_group_members(session: Session, group_key: UUID) -> Sequence[Job]:
    """Resolve a preview/list group key to sibling jobs.

    ``group_key`` is either ``job_group_id`` or a legacy job ``external_id``
    (when ``job_group_id`` is NULL).
    """
    by_group = list(list_by_job_group_id(session, group_key))
    if by_group:
        return by_group
    job = get_by_external_id(session, group_key)
    if job is None or job.job_type != JobType.GENERATION.value or job.deleted_at is not None:
        return []
    if job.job_group_id is not None:
        return list(list_by_job_group_id(session, job.job_group_id))
    return [job]


def save(session: Session, job: Job) -> Job:
    return base.save(session, job)
