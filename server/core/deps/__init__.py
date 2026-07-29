from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from core.clients.db import DatabaseClient
from core.clients.openrouter import OpenRouterClient


def get_db_session(request: Request) -> Iterator[Session]:
    db: DatabaseClient = request.app.state.db
    session = db.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_openrouter_client(request: Request) -> OpenRouterClient:
    client: OpenRouterClient | None = request.app.state.openrouter
    if client is None:
        raise HTTPException(status_code=503, detail="OpenRouter is not configured")
    return client


SessionDep = Annotated[Session, Depends(get_db_session)]
OpenRouterDep = Annotated[OpenRouterClient, Depends(get_openrouter_client)]
