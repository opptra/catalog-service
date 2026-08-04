from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from core.clients.db import DatabaseClient
from core.clients.gcs import GcsClient
from core.clients.google_auth import GoogleAuthClient
from core.clients.openrouter import OpenRouterClient
from core.clients.workflows import WorkflowsClient
from entities.user_service.user import User


def _session(db: DatabaseClient) -> Iterator[Session]:
    """One session per request. No request-level transaction: repository
    writes commit immediately (see repositories.base), so partial progress
    is never rolled back by a later failure in the same request.
    """
    session = db.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_catalog_session(request: Request) -> Iterator[Session]:
    yield from _session(request.app.state.catalog_db)


def get_user_session(request: Request) -> Iterator[Session]:
    yield from _session(request.app.state.user_db)


CatalogSessionDep = Annotated[Session, Depends(get_catalog_session)]
UserSessionDep = Annotated[Session, Depends(get_user_session)]


def get_google_auth_client(request: Request) -> GoogleAuthClient:
    return request.app.state.google_auth


GoogleAuthClientDep = Annotated[GoogleAuthClient, Depends(get_google_auth_client)]


def get_openrouter_client(request: Request) -> OpenRouterClient:
    client: OpenRouterClient | None = request.app.state.openrouter
    if client is None:
        raise HTTPException(status_code=503, detail="OpenRouter is not configured")
    return client


OpenRouterDep = Annotated[OpenRouterClient, Depends(get_openrouter_client)]


def get_gcs_client(request: Request) -> GcsClient:
    client: GcsClient | None = request.app.state.gcs
    if client is None:
        raise HTTPException(status_code=503, detail="GCS is not configured")
    return client


GcsDep = Annotated[GcsClient, Depends(get_gcs_client)]


def get_workflows_client(request: Request) -> WorkflowsClient:
    client: WorkflowsClient | None = request.app.state.workflows
    if client is None:
        raise HTTPException(status_code=503, detail="Cloud Workflows is not configured")
    return client


WorkflowsDep = Annotated[WorkflowsClient, Depends(get_workflows_client)]


def get_current_user(request: Request) -> User:
    """The authenticated user resolved by ``GoogleUserAuthenticator``.

    ``AuthAPIRoute`` runs the authenticator before any handler, which verifies
    the Google token, looks up the user, and binds it to ``request.state.user``,
    so this is just an accessor — it never verifies tokens or hits the database.
    """
    return request.state.user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def get_service_client_id(request: Request) -> str:
    """Client id authenticated on an ``@internal_api`` route (``client-id`` header)."""
    client_id = getattr(request.state, "service_client_id", None)
    if not client_id:
        raise HTTPException(status_code=401, detail="Missing service client")
    return client_id


ServiceClientIdDep = Annotated[str, Depends(get_service_client_id)]
