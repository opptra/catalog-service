"""Issue and verify catalog-service session JWTs (HS256).

Claims stay small: sub (user.external_id), iat, exp, iss, aud. Lifetime is
absolute from issue time — no idle sliding or re-issue on activity.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt

from core.config import settings

_ALGORITHM = "HS256"
_ISSUER = "catalog-service"
_AUDIENCE = "catalog-service"
# Small clock-skew tolerance when verifying exp/iat.
_LEEWAY_SECONDS = 30


class SessionJwtError(Exception):
    """Raised when a session JWT cannot be decoded or fails validation."""


def encode(*, user_external_id: UUID) -> str:
    """Mint a session JWT valid for ``settings.session_ttl_hours`` from now."""
    now = datetime.now(UTC)
    exp = now + timedelta(hours=settings.session_ttl_hours)
    payload = {
        "sub": str(user_external_id),
        "iat": now,
        "exp": exp,
        "iss": _ISSUER,
        "aud": _AUDIENCE,
    }
    return jwt.encode(payload, settings.session_jwt_secret, algorithm=_ALGORITHM)


def decode(token: str) -> dict[str, Any]:
    """Verify signature, iss, aud, and exp. Returns claims on success."""
    try:
        return jwt.decode(
            token,
            settings.session_jwt_secret,
            algorithms=[_ALGORITHM],
            issuer=_ISSUER,
            audience=_AUDIENCE,
            leeway=_LEEWAY_SECONDS,
        )
    except jwt.PyJWTError as exc:
        raise SessionJwtError(str(exc)) from exc


def session_max_age_seconds() -> int:
    return int(timedelta(hours=settings.session_ttl_hours).total_seconds())
