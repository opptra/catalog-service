from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from core.config import settings
from core.deps import OpenRouterDep, SessionDep
from core.exceptions import GenerateError, GenerateInputError, ProductNotFoundError
from dto.generate import GenerateJobRequest, GenerateJobResponse
from services.generate import run_generate_job

router = APIRouter(tags=["generate"])


def _output_root() -> Path:
    root = Path(settings.generate_output_dir)
    if not root.is_absolute():
        root = Path.cwd() / root
    return root.resolve()


@router.post("/jobs/generate", response_model=GenerateJobResponse)
def create_generate_job(
    body: GenerateJobRequest,
    openrouter: OpenRouterDep,
    session: SessionDep,
) -> GenerateJobResponse:
    try:
        return run_generate_job(
            openrouter,
            body,
            session=session if body.persist_to_db else None,
        )
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GenerateInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GenerateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/assets/{asset_path:path}")
def get_generated_asset(asset_path: str) -> FileResponse:
    root = _output_root()
    target = (root / asset_path).resolve()
    if not str(target).startswith(str(root)):
        raise HTTPException(status_code=400, detail="Invalid asset path")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(target)
