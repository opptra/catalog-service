from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/")
def root() -> dict[str, str]:
    return {"message": "Catalog Service API is ready."}


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
