from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.clients.db import DatabaseClient
from core.clients.openrouter import OpenRouterClient
from core.config import settings
from routers import health, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = DatabaseClient(settings)
    app.state.db = db
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
        db.close()


app = FastAPI(title="Catalog Service", lifespan=lifespan)

# Same /api prefix locally and behind nginx — client always calls /api/...
API_PREFIX = "/api"
app.include_router(health.router, prefix=API_PREFIX)
app.include_router(users.router, prefix=API_PREFIX)
