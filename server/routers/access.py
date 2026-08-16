"""Access grants for the current user (brands and brand user management)."""

from fastapi import HTTPException

from core.auth import SecureAPIRouter
from core.deps import BrandAccessDep, CatalogSessionDep, CurrentUserDep, UserSessionDep
from core.exceptions import (
    EmailDomainNotAllowedError,
    RoleNotFoundError,
)
from dto.request.access import InviteBrandUserRequest
from dto.response.access import (
    AccessibleBrandResponse,
    BrandUserResponse,
    InviteBrandUserResponse,
)
from services import access as access_service

router = SecureAPIRouter(prefix="/access", tags=["access"])


@router.get("/brands", response_model=list[AccessibleBrandResponse])
def list_accessible_brands(
    user: CurrentUserDep,
    user_session: UserSessionDep,
    catalog_session: CatalogSessionDep,
) -> list[AccessibleBrandResponse]:
    return access_service.list_accessible_brands(user_session, catalog_session, user.id)


@router.get("/brand/users", response_model=list[BrandUserResponse])
def list_brand_users(
    user: CurrentUserDep,
    user_session: UserSessionDep,
    catalog_session: CatalogSessionDep,
    brand_external_id: BrandAccessDep,
) -> list[BrandUserResponse]:
    # BrandAccessDep already verified the grant; service re-checks and loads users.
    return access_service.list_brand_users(
        user_session,
        catalog_session,
        actor=user,
        brand_external_id=brand_external_id,
    )


@router.post("/brands/users/invite", response_model=InviteBrandUserResponse)
def invite_brand_user(
    body: InviteBrandUserRequest,
    user: CurrentUserDep,
    user_session: UserSessionDep,
    catalog_session: CatalogSessionDep,
    brand_external_id: BrandAccessDep,
) -> InviteBrandUserResponse:
    try:
        return access_service.invite_brand_user(
            user_session,
            catalog_session,
            actor=user,
            brand_external_id=brand_external_id,
            email=str(body.email),
        )
    except EmailDomainNotAllowedError as exc:
        raise HTTPException(
            status_code=422,
            detail="Only @opptra.com email addresses can be invited.",
        ) from exc
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
