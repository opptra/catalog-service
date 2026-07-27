from sqlalchemy import select
from sqlalchemy.orm import Session

from core.exceptions import UserNotFoundError
from core.models.user import User


def get_user_by_external_id(session: Session, external_id: str) -> User:
    user = session.scalar(select(User).where(User.external_id == external_id))
    if user is None:
        raise UserNotFoundError(external_id)
    return user
