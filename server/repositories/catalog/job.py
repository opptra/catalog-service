from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.catalog.job import Job


def get_by_id(session: Session, job_id: int) -> Job | None:
    return session.get(Job, job_id)


def get_by_external_id(session: Session, external_id: UUID) -> Job | None:
    return session.scalar(select(Job).where(Job.external_id == external_id))
