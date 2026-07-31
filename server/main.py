from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.clients.db import DatabaseClient
from core.clients.google_auth import GoogleAuthClient
from core.clients.openrouter import OpenRouterClient
from core.config import settings
from core.middleware.auth import AuthMiddleware
from routers import auth, health, users


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
    try:
        yield
    finally:
        if app.state.openrouter is not None:
            app.state.openrouter.close()
        catalog_db.close()
        user_db.close()


app = FastAPI(title="Catalog Service", lifespan=lifespan)

# Added first so it runs innermost; CORS (added below) stays outermost and
# attaches headers even to 401 responses from the auth middleware.
app.add_middleware(AuthMiddleware, public_paths=settings.public_paths)

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
