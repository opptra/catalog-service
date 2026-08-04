from collections.abc import Callable
from typing import Any

from fastapi import APIRouter
from fastapi.routing import APIRoute
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core.auth.authenticators import AUTHENTICATORS, AuthError
from core.auth.policy import get_auth_policy, has_internal_suffix


class AuthAPIRoute(APIRoute):
    """An ``APIRoute`` that authenticates before dispatching to its endpoint.

    Starlette has already matched the route by the time ``get_route_handler``'s
    returned callable runs, so ``self.endpoint`` is the exact handler for this
    request — no need to re-resolve it against ``app.routes``.
    """

    def get_route_handler(self) -> Callable[[Request], Any]:
        original_handler = super().get_route_handler()
        policy = get_auth_policy(self.endpoint)
        authenticator = AUTHENTICATORS[policy]

        async def handler(request: Request) -> Response:
            try:
                await authenticator.authenticate(request)
            except AuthError as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
            return await original_handler(request)

        return handler


class SecureAPIRouter(APIRouter):
    """An ``APIRouter`` whose routes are auth-checked via ``AuthAPIRoute``.

    Handlers marked ``@internal_api`` automatically get ``/internal`` appended
    to their path, so route declaration and the internal/external distinction
    stay in one place.
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("route_class", AuthAPIRoute)
        super().__init__(**kwargs)

    def add_api_route(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        if has_internal_suffix(endpoint):
            path = f"{path}/internal"
        super().add_api_route(path, endpoint, **kwargs)
