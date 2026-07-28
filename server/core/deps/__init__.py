from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from core.clients.db import DatabaseClient


def get_db_session(request: Request) -> Iterator[Session]:
    db: DatabaseClient = request.app.state.db
    session = db.session_factory()
    try:
        yield session
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_db_session)]
