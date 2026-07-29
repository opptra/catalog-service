from uuid import UUID

from sqlalchemy.orm import Session

from core.exceptions import UserNotFoundError
from entities.user_service.user import User
from repositories.user_service import user as user_repository


def get_user_by_external_id(session: Session, external_id: UUID) -> User:
    user = user_repository.get_by_external_id(session, external_id)
    if user is None:
        raise UserNotFoundError(str(external_id))
    return user
