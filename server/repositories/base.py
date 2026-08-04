from collections.abc import Sequence

from sqlalchemy.orm import Session


def save[T](session: Session, instance: T) -> T:
    """Persist an insert or update immediately.

    Each write commits on its own, so callers never manage commit/flush and
    already-persisted state survives a later failure in the same request.
    """
    session.add(instance)
    session.commit()
    session.refresh(instance)
    return instance


def save_all[T](session: Session, instances: Sequence[T]) -> list[T]:
    """Persist many inserts/updates in one commit."""
    if not instances:
        return []
    session.add_all(instances)
    session.commit()
    for instance in instances:
        session.refresh(instance)
    return list(instances)


def delete(session: Session, instance: object) -> None:
    """Delete an instance and commit immediately."""
    session.delete(instance)
    session.commit()
