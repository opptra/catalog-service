from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.clients.db import DatabaseClient
from core.clients.gcs import GcsClient
from core.clients.google_auth import GoogleAuthClient
from core.clients.openrouter import OpenRouterClient
from core.clients.workflows import WorkflowsClient
from core.config import settings
from routers import auth, health, job, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    catalog_db = DatabaseClient(settings.catalog_database_url)
    user_db = DatabaseClient(settings.user_database_url)
    app.state.catalog_db = catalog_db
    app.state.user_db = user_db
    app.state.google_auth = GoogleAuthClient(settings.google_client_id)
    app.state.openrouter = (
        OpenRouterClient(
            settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
        )
        if settings.openrouter_api_key
        else None
    )
    app.state.gcs = (
        GcsClient(settings.gcs_bucket, project=settings.google_cloud_project)
        if settings.gcs_bucket
        else None
    )
    app.state.workflows = (
        WorkflowsClient(settings.google_cloud_project, settings.workflows_location)
        if settings.google_cloud_project
        else None
    )
    try:
        yield
    finally:
        if app.state.openrouter is not None:
            app.state.openrouter.close()
        catalog_db.close()
        user_db.close()


app = FastAPI(title="Catalog Service", lifespan=lifespan)

# Auth is enforced per-route by AuthAPIRoute (see core.auth), not middleware.
# CORS still needs to be outermost so it attaches headers to 401 responses too.
if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Same /api prefix locally and behind nginx — client always calls /api/...
API_PREFIX = "/api"
app.include_router(health.router, prefix=API_PREFIX)
app.include_router(users.router, prefix=API_PREFIX)
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(job.router, prefix=API_PREFIX)
