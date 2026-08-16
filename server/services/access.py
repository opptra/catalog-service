from uuid import UUID

from sqlalchemy.orm import Session

from core.exceptions import (
    EmailDomainNotAllowedError,
    RoleNotFoundError,
)
from dto.response.access import (
    AccessibleBrandResponse,
    BrandUserResponse,
    InviteBrandUserResponse,
)
from entities.user_service.user import User
from entities.user_service.user_access_grant import UserAccessGrant
from repositories.catalog import brand as catalog_brand_repository
from repositories.user_service import role as role_repository
from repositories.user_service import user as user_repository
from repositories.user_service import user_access_grant as grant_repository
from services import authorization

_DEFAULT_ROLE_NAME = "USER"
_ALLOWED_EMAIL_DOMAIN = "opptra.com"


def list_accessible_brands(
    user_session: Session,
    catalog_session: Session,
    user_id: int,
) -> list[AccessibleBrandResponse]:
    grants = grant_repository.list_brand_access_for_user(user_session, user_id)
    if not grants:
        return []

    catalog_brands = catalog_brand_repository.list_by_user_service_brand_ids(
        catalog_session, [grant.external_id for grant in grants]
    )
    catalog_brand_by_user_service_id = {
        brand.user_service_brand_id: brand for brand in catalog_brands
    }

    result: list[AccessibleBrandResponse] = []
    for grant in grants:
        catalog_brand = catalog_brand_by_user_service_id.get(grant.external_id)
        if catalog_brand is None:
            continue
        result.append(
            AccessibleBrandResponse(
                external_id=catalog_brand.external_id,
                name=catalog_brand.name,
                granted_at=grant.granted_at,
            )
        )
    return result


def list_brand_users(
    user_session: Session,
    catalog_session: Session,
    *,
    actor: User,
    brand_external_id: UUID,
) -> list[BrandUserResponse]:
    application, user_brand = authorization.assert_brand_access(
        user_session,
        catalog_session,
        actor=actor,
        brand_external_id=brand_external_id,
    )
    rows = grant_repository.list_users_for_brand_application(
        user_session,
        brand_id=user_brand.id,
        application_id=application.id,
    )
    return [
        BrandUserResponse(
            external_id=row.external_id,
            name=row.name,
            email=row.email,
            granted_at=row.granted_at,
            has_signed_in=bool(row.has_signed_in),
        )
        for row in rows
    ]


def invite_brand_user(
    user_session: Session,
    catalog_session: Session,
    *,
    actor: User,
    brand_external_id: UUID,
    email: str,
) -> InviteBrandUserResponse:
    normalized_email = email.strip().lower()
    if not _is_allowed_email(normalized_email):
        raise EmailDomainNotAllowedError(normalized_email)

    application, user_brand = authorization.assert_brand_access(
        user_session,
        catalog_session,
        actor=actor,
        brand_external_id=brand_external_id,
    )
    role = role_repository.get_by_name(user_session, _DEFAULT_ROLE_NAME)
    if role is None:
        raise RoleNotFoundError(_DEFAULT_ROLE_NAME)

    invitee = user_repository.get_by_email(user_session, normalized_email)
    created_user = False
    if invitee is None:
        local_part = normalized_email.split("@", 1)[0]
        invitee = user_repository.create(
            user_session,
            name=local_part,
            email=normalized_email,
            google_sub=None,
        )
        created_user = True

    existing_grant = grant_repository.get_grant(
        user_session,
        user_id=invitee.id,
        brand_id=user_brand.id,
        application_id=application.id,
    )
    created_grant = False
    if existing_grant is None:
        existing_grant = grant_repository.save(
            user_session,
            UserAccessGrant(
                user_id=invitee.id,
                brand_id=user_brand.id,
                application_id=application.id,
                role_id=role.id,
            ),
        )
        created_grant = True

    return InviteBrandUserResponse(
        external_id=invitee.external_id,
        name=invitee.name,
        email=invitee.email,
        granted_at=existing_grant.created_at,
        has_signed_in=invitee.google_sub is not None,
        created=created_user or created_grant,
    )


def _is_allowed_email(email: str) -> bool:
    return email.endswith(f"@{_ALLOWED_EMAIL_DOMAIN}")
