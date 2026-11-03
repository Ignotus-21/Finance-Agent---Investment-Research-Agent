"""
FastAPI Dependencies Module.
Provides Google OIDC bearer-token authentication verification and
Dependency Injection container access.
"""

import logging
from typing import Any

from fastapi import Header, HTTPException
from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from starlette.concurrency import run_in_threadpool

from src.config import settings
from src.core.container import ApplicationContainer, container

logger = logging.getLogger(__name__)

_TRANSPORT = google_requests.Request()


async def get_container() -> ApplicationContainer:
    """Provide application Dependency Injection container instance."""
    return container


def _read_bearer_token(authorization: str | None) -> str:
    """Extract Bearer token from Authorization header or raise HTTP 401."""
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header. Bearer token required.",
        )

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization scheme. Bearer <token> required.",
        )

    if not parts[1]:
        raise HTTPException(
            status_code=401,
            detail="Invalid or malformed Bearer token.",
        )

    return parts[1]


def _verify_google_id_token(token: str, audiences: tuple[str, ...]) -> dict[str, Any]:
    """Verify a Google-signed OIDC ID token against configured audiences."""
    claims: dict[str, Any] = id_token.verify_oauth2_token(
        token, _TRANSPORT, audience=list(audiences)
    )
    return claims


async def verify_auth_token(
    authorization: str | None = Header(None),
) -> str:
    """
    Authenticate caller via Google OIDC ID token verification and return
    the verified principal (`email` or `sub`) for compliance audit logging.
    """
    token = _read_bearer_token(authorization)

    audiences = settings.allowed_audiences
    if not audiences:
        logger.warning(
            "auth_allowed_audiences is unset: bearer credential accepted without "
            "verification. This is a development-only path."
        )
        return f"unverified-dev-{token[:6]}"

    try:
        claims = await run_in_threadpool(_verify_google_id_token, token, audiences)
    except (GoogleAuthError, ValueError) as exc:
        logger.warning("Bearer token rejected: %s", exc)
        raise HTTPException(
            status_code=401,
            detail="Bearer token failed verification.",
        ) from exc

    identity = claims.get("email") or claims.get("sub")
    if not identity:
        logger.warning("Verified token carried neither an email nor a sub claim.")
        raise HTTPException(
            status_code=401,
            detail="Bearer token failed verification.",
        )

    return str(identity)
