"""Declarative route auth: annotate handlers, ``SecureAPIRouter`` enforces it.

- ``@internal_api`` — service-to-service route, authenticated via ``client-id`` /
  ``client-token`` headers, automatically exposed with a ``/internal`` path suffix.
- ``@no_auth`` — route is exempt from authentication entirely.
- no annotation — default, authenticated via the ``catalog_session`` httpOnly JWT.

Routers must use ``SecureAPIRouter`` (not the plain ``fastapi.APIRouter``) for
these annotations to take effect.
"""

from core.auth.policy import AuthPolicy, internal_api, no_auth
from core.auth.routing import SecureAPIRouter

__all__ = [
    "AuthPolicy",
    "SecureAPIRouter",
    "internal_api",
    "no_auth",
]
