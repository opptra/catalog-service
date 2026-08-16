from collections.abc import Callable
from enum import StrEnum

_POLICY_ATTR = "_catalog_auth_policy"
_INTERNAL_SUFFIX_ATTR = "_catalog_internal_suffix"


class AuthPolicy(StrEnum):
    """Which authenticator a route requires. Default (no annotation) is GOOGLE_USER
    (browser session cookie via ``SessionAuthenticator``).
    """

    GOOGLE_USER = "google_user"
    INTERNAL_CLIENT = "internal_client"
    PUBLIC = "public"


def internal_api[F: Callable[..., object]](handler: F) -> F:
    """Mark a handler as an internal (service-to-service) API.

    The route is authenticated with ``client-id`` + ``client-token`` headers
    (see ``InternalClientAuthenticator``) instead of a browser session cookie, and
    ``SecureAPIRouter`` automatically appends ``/internal`` to its path.
    """
    setattr(handler, _POLICY_ATTR, AuthPolicy.INTERNAL_CLIENT)
    setattr(handler, _INTERNAL_SUFFIX_ATTR, True)
    return handler


def no_auth[F: Callable[..., object]](handler: F) -> F:
    """Mark a handler as exempt from authentication entirely."""
    setattr(handler, _POLICY_ATTR, AuthPolicy.PUBLIC)
    return handler


def get_auth_policy(handler: object) -> AuthPolicy:
    return getattr(handler, _POLICY_ATTR, AuthPolicy.GOOGLE_USER)


def has_internal_suffix(handler: object) -> bool:
    return bool(getattr(handler, _INTERNAL_SUFFIX_ATTR, False))
