from collections.abc import Sequence

from sqlalchemy import Row
from sqlalchemy.orm import Session

from repositories.user_service import user_access_grant as grant_repository


def list_brand_access_for_user(session: Session, user_id: int) -> Sequence[Row]:
    return grant_repository.list_brand_access_for_user(session, user_id)
