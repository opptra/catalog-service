from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from core.clients.db import DatabaseClient
from core.config import settings
from routers import health, users

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = DatabaseClient(settings.database_url)
    app.state.db = db
    try:
        yield
    finally:
        db.close()


app = FastAPI(title="Catalog Service", lifespan=lifespan)

app.include_router(health.router)
app.include_router(users.router)
