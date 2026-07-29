from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from core.clients.db import DatabaseClient


def get_catalog_session(request: Request) -> Iterator[Session]:
    db: DatabaseClient = request.app.state.catalog_db
    session = db.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_user_session(request: Request) -> Iterator[Session]:
    db: DatabaseClient = request.app.state.user_db
    session = db.session_factory()
    try:
        yield session
    finally:
        session.close()


CatalogSessionDep = Annotated[Session, Depends(get_catalog_session)]
UserSessionDep = Annotated[Session, Depends(get_user_session)]
