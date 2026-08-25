"""Laptop entrypoint — never imported by the committed app.

Start from ``server/``:

    uvicorn local.app:app --reload

Production / CI stay on ``uvicorn main:app``.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

# load_dotenv does not override existing keys. Blank the bucket so prod lifespan
# does not construct GcsClient (which needs ADC) before this overlay replaces it.
os.environ["GCS_BUCKET"] = ""

from core.auth.authenticators import AUTHENTICATORS
from core.auth.policy import AuthPolicy
from local.auth import LocalSessionAuthenticator

# AuthAPIRoute closes over AUTHENTICATORS at route construction. Patch first.
AUTHENTICATORS[AuthPolicy.GOOGLE_USER] = LocalSessionAuthenticator()

from main import API_PREFIX, app  # noqa: E402
from local.jobs import LocalJobOrchestrator  # noqa: E402
from local.routers.storage import router as local_storage_router  # noqa: E402
from local.storage import LocalStorageClient  # noqa: E402

_STORAGE_DIR = os.environ.get("LOCAL_STORAGE_DIR") or "../local-data/objects"

_prod_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _local_lifespan(app_instance: Any):
    async with _prod_lifespan(app_instance):
        app_instance.state.gcs = LocalStorageClient(_STORAGE_DIR)
        app_instance.state.dropbox = None
        app_instance.state.workflows = LocalJobOrchestrator(app_instance)
        yield


app.router.lifespan_context = _local_lifespan
app.include_router(local_storage_router, prefix=API_PREFIX)
