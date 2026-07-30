from collections.abc import Sequence

from sqlalchemy import Row, select
from sqlalchemy.orm import Session

from entities.user_service.brand import Brand
from entities.user_service.user_access_grant import UserAccessGrant


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
