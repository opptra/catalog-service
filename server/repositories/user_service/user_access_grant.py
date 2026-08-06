from collections.abc import Sequence

from sqlalchemy import Row, select
from sqlalchemy.orm import Session

from entities.user_service.brand import Brand
from entities.user_service.user import User
from entities.user_service.user_access_grant import UserAccessGrant
from repositories import base


def list_brand_access_for_user(session: Session, user_id: int) -> Sequence[Row]:
    return session.execute(
        select(
            Brand.external_id,
            Brand.name,
            UserAccessGrant.created_at.label("granted_at"),
        )
        .join(UserAccessGrant, UserAccessGrant.brand_id == Brand.id)
        .where(UserAccessGrant.user_id == user_id)
        .order_by(Brand.name)
    ).all()


def get_grant(
    session: Session,
    *,
    user_id: int,
    brand_id: int,
    application_id: int,
) -> UserAccessGrant | None:
    return session.scalar(
        select(UserAccessGrant).where(
            UserAccessGrant.user_id == user_id,
            UserAccessGrant.brand_id == brand_id,
            UserAccessGrant.application_id == application_id,
        )
    )


def list_users_for_brand_application(
    session: Session,
    *,
    brand_id: int,
    application_id: int,
) -> Sequence[Row]:
    """Users with a grant for the brand+application, oldest grants first."""
    return session.execute(
        select(
            User.external_id,
            User.name,
            User.email,
            UserAccessGrant.created_at.label("granted_at"),
            (User.google_sub.is_not(None)).label("has_signed_in"),
        )
        .join(UserAccessGrant, UserAccessGrant.user_id == User.id)
        .where(
            UserAccessGrant.brand_id == brand_id,
            UserAccessGrant.application_id == application_id,
        )
        .order_by(UserAccessGrant.created_at.asc(), User.email.asc())
    ).all()


def save(session: Session, grant: UserAccessGrant) -> UserAccessGrant:
    return base.save(session, grant)
