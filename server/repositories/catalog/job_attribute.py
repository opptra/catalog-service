from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from entities.catalog.job_attribute import JobAttribute


def get_by_id(session: Session, job_attribute_id: int) -> JobAttribute | None:
    return session.get(JobAttribute, job_attribute_id)


def get_by_external_id(session: Session, external_id: UUID) -> JobAttribute | None:
    return session.scalar(select(JobAttribute).where(JobAttribute.external_id == external_id))


def list_by_job_id(session: Session, job_id: int) -> Sequence[JobAttribute]:
    return session.scalars(select(JobAttribute).where(JobAttribute.job_id == job_id)).all()
