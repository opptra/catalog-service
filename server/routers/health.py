from core.auth import SecureAPIRouter, no_auth

router = SecureAPIRouter(tags=["health"])


@router.get("/")
@no_auth
def root() -> dict[str, str]:
    return {"message": "Catalog Service API is ready."}


@router.get("/health")
@no_auth
def health() -> dict[str, str]:
    return {"status": "ok"}
