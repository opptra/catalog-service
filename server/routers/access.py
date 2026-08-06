"""Access grants for the current user (brands and brand user management)."""

from uuid import UUID

from fastapi import HTTPException

from core.auth import SecureAPIRouter
from core.deps import CatalogSessionDep, CurrentUserDep, UserSessionDep
from core.exceptions import (
    ApplicationNotFoundError,
    BrandAccessDeniedError,
    BrandNotFoundError,
    EmailDomainNotAllowedError,
    RoleNotFoundError,
    UserServiceBrandNotFoundError,
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


@router.get("/brands/{brand_external_id}/users", response_model=list[BrandUserResponse])
def list_brand_users(
    brand_external_id: UUID,
    user: CurrentUserDep,
    user_session: UserSessionDep,
    catalog_session: CatalogSessionDep,
) -> list[BrandUserResponse]:
    try:
        return access_service.list_brand_users(
            user_session,
            catalog_session,
            actor=user,
            brand_external_id=brand_external_id,
        )
    except BrandNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UserServiceBrandNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApplicationNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except BrandAccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/brands/users/invite", response_model=InviteBrandUserResponse)
def invite_brand_user(
    body: InviteBrandUserRequest,
    user: CurrentUserDep,
    user_session: UserSessionDep,
    catalog_session: CatalogSessionDep,
) -> InviteBrandUserResponse:
    try:
        return access_service.invite_brand_user(
            user_session,
            catalog_session,
            actor=user,
            brand_external_id=body.brand_external_id,
            email=str(body.email),
        )
    except EmailDomainNotAllowedError as exc:
        raise HTTPException(
            status_code=422,
            detail="Only @opptra.com email addresses can be invited.",
        ) from exc
    except BrandNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UserServiceBrandNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApplicationNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except BrandAccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
