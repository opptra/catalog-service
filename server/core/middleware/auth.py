from collections.abc import Iterable

from google.auth.exceptions import GoogleAuthError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core.exceptions import UserNotFoundError
from services import users as user_service


class AuthMiddleware(BaseHTTPMiddleware):
    """Verifies the Google ID token on every request and binds the user.

    Runs before any route handler:
      - public/allowlisted paths (and CORS preflight) skip the check entirely;
      - otherwise the ``Authorization: Bearer <google-id-token>`` header is
        verified and the existing user is looked up and attached to
        ``request.state.user``. Missing/invalid token or unknown user is
        rejected here, so handlers can assume a valid user is present.

    The middleware only looks up users — it never creates them. User creation
    stays in the login endpoint (``POST /auth/google``).
    """

    def __init__(self, app, public_paths: Iterable[str]) -> None:
        super().__init__(app)
        self._public_paths = set(public_paths)

    def _is_public(self, request: Request) -> bool:
        if request.method == "OPTIONS":
            return True
        return request.url.path in self._public_paths

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if self._is_public(request):
            return await call_next(request)

        token = _extract_bearer_token(request)
        if token is None:
            return JSONResponse({"detail": "Missing bearer token"}, status_code=401)

        google_client = request.app.state.google_auth
        try:
            claims = google_client.verify_id_token(token)
        except (ValueError, GoogleAuthError):
            return JSONResponse({"detail": "Invalid Google ID token"}, status_code=401)

        try:
            user = await run_in_threadpool(_lookup_user, request, claims["sub"])
        except UserNotFoundError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=401)

        request.state.user = user
        return await call_next(request)


def _extract_bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization")
    if not header:
        return None
    scheme, _, credentials = header.partition(" ")
    if scheme.lower() != "bearer" or not credentials.strip():
        return None
    return credentials.strip()


def _lookup_user(request: Request, google_sub: str):
    session = request.app.state.user_db.session_factory()
    try:
        return user_service.get_user_by_google_sub(session, google_sub)
    finally:
        session.close()
