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


def list_generation_by_created_by(
    session: Session, created_by: UUID
) -> Sequence[Job]:
    """Newest generation jobs first for the given user."""
    return session.scalars(
        select(Job)
        .where(
            Job.created_by == created_by,
            Job.job_type == JobType.GENERATION.value,
        )
        .order_by(Job.created_at.desc())
    ).all()


def save(session: Session, job: Job) -> Job:
    return base.save(session, job)
