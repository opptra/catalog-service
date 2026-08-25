"""Brand-scoped authorization guards.

Authentication (valid session) is not enough — brand routes must verify the
caller has a grant to the brand they touch. Grant rows live in user_service;
job → brand resolution lives in catalog_service.
"""

from uuid import UUID

from sqlalchemy.orm import Session

from core.exceptions import (
    ApplicationNotFoundError,
    AttributeValueNotFoundError,
    BrandAccessDeniedError,
    BrandNotFoundError,
    JobNotFoundError,
    SkuGenerationJobNotFoundError,
    UserServiceBrandNotFoundError,
)
from entities.user_service.application import Application
from entities.user_service.brand import Brand as UserServiceBrand
from entities.user_service.user import User
from repositories.catalog import brand as catalog_brand_repository
from repositories.catalog import job as job_repository
from repositories.catalog import sku_generation_job as sku_generation_job_repository
from repositories.catalog import (
    sku_marketplace_attribute_value as attribute_value_repository,
)
from repositories.user_service import application as application_repository
from repositories.user_service import brand as user_brand_repository
from repositories.user_service import user_access_grant as grant_repository

# Product name in UI is Listing Studio; the applications.name row is catalog-service.
_LISTING_STUDIO_APPLICATION_NAME = "catalog-service"


def assert_brand_access(
    user_session: Session,
    catalog_session: Session,
    *,
    actor: User,
    brand_external_id: UUID,
) -> tuple[Application, UserServiceBrand]:
    """Raise when the actor has no grant to the catalog brand.

    Returns the application and user-service brand row for callers that need
    them (e.g. invite / list brand users).
    """
    application = application_repository.get_by_name(user_session, _LISTING_STUDIO_APPLICATION_NAME)
    if application is None:
        raise ApplicationNotFoundError(_LISTING_STUDIO_APPLICATION_NAME)

    catalog_brand = catalog_brand_repository.get_by_external_id(catalog_session, brand_external_id)
    if catalog_brand is None or catalog_brand.user_service_brand_id is None:
        raise BrandNotFoundError(f"brand_external_id={brand_external_id}")

    user_brand = user_brand_repository.get_by_external_id(
        user_session, catalog_brand.user_service_brand_id
    )
    if user_brand is None:
        raise UserServiceBrandNotFoundError(str(brand_external_id))

    actor_grant = grant_repository.get_grant(
        user_session,
        user_id=actor.id,
        brand_id=user_brand.id,
        application_id=application.id,
    )
    if actor_grant is None:
        raise BrandAccessDeniedError(str(brand_external_id))

    return application, user_brand


def assert_job_access(
    user_session: Session,
    catalog_session: Session,
    *,
    actor: User,
    job_external_id: UUID,
) -> UUID:
    """Resolve job → brand and assert grant. Returns brand_external_id."""
    job = job_repository.get_by_external_id(catalog_session, job_external_id)
    if job is None or job.brand_id is None:
        raise JobNotFoundError(f"Job not found: {job_external_id}")

    assert_brand_access(
        user_session,
        catalog_session,
        actor=actor,
        brand_external_id=job.brand_id,
    )
    return job.brand_id


def assert_job_group_access(
    user_session: Session,
    catalog_session: Session,
    *,
    actor: User,
    job_group_id: UUID,
) -> UUID:
    """Resolve any job in the group → brand and assert grant. Returns brand_external_id."""
    members = job_repository.list_group_members(catalog_session, job_group_id)
    if not members:
        raise JobNotFoundError(f"Job group not found: {job_group_id}")
    job = members[0]
    if job.brand_id is None:
        raise JobNotFoundError(f"Job group not found: {job_group_id}")
    assert_brand_access(
        user_session,
        catalog_session,
        actor=actor,
        brand_external_id=job.brand_id,
    )
    return job.brand_id


def assert_sku_generation_job_access(
    user_session: Session,
    catalog_session: Session,
    *,
    actor: User,
    sku_generation_job_external_id: UUID,
) -> UUID:
    """Resolve sku_generation_job → job → brand and assert grant."""
    sku_job = sku_generation_job_repository.get_by_external_id(
        catalog_session, sku_generation_job_external_id
    )
    if sku_job is None:
        raise SkuGenerationJobNotFoundError(
            f"SKU generation job not found: {sku_generation_job_external_id}"
        )

    job = job_repository.get_by_id(catalog_session, sku_job.job_id)
    if job is None or job.brand_id is None:
        raise JobNotFoundError(
            f"Job not found for sku generation job: {sku_generation_job_external_id}"
        )

    assert_brand_access(
        user_session,
        catalog_session,
        actor=actor,
        brand_external_id=job.brand_id,
    )
    return job.brand_id


def assert_attribute_value_access(
    user_session: Session,
    catalog_session: Session,
    *,
    actor: User,
    value_external_id: UUID,
) -> UUID:
    """Resolve attribute value → sku_generation_job → job → brand and assert grant."""
    value = attribute_value_repository.get_latest_by_external_id(catalog_session, value_external_id)
    if value is None:
        raise AttributeValueNotFoundError(f"Attribute value not found: {value_external_id}")

    sku_job = sku_generation_job_repository.get_by_id(catalog_session, value.sku_generation_job_id)
    if sku_job is None:
        raise SkuGenerationJobNotFoundError(
            f"SKU generation job not found for value: {value_external_id}"
        )

    job = job_repository.get_by_id(catalog_session, sku_job.job_id)
    if job is None or job.brand_id is None:
        raise JobNotFoundError(f"Job not found for attribute value: {value_external_id}")

    assert_brand_access(
        user_session,
        catalog_session,
        actor=actor,
        brand_external_id=job.brand_id,
    )
    return job.brand_id
