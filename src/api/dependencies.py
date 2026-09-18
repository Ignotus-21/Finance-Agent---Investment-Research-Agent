"""
FastAPI Dependencies Module.
Provides authentication verification and Dependency Injection container access.
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

# One adapter, reused. google-auth caches Google's signing certificates on the
# session underneath it, so a new adapter per request would re-fetch the JWKS
# on every call and put an outbound HTTP round trip in the hot path.
_TRANSPORT = google_requests.Request()


async def get_container() -> ApplicationContainer:
    """Provides application DI container instance."""
    return container


def _read_bearer_token(authorization: str | None) -> str:
    """Pull the credential out of the Authorization header, or raise 401."""
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header. Bearer token required."
        )

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization scheme. Bearer <token> required."
        )

    if not parts[1]:
        raise HTTPException(
            status_code=401,
            detail="Invalid or malformed Bearer token."
        )

    return parts[1]


def _verify_google_id_token(token: str) -> dict[str, Any]:
    """
    Verify a Google-signed OIDC ID token.

    Checks the RS256 signature against Google's published certificates, the
    issuer, the expiry, and the audience. Cloud Run forwards the same
    Authorization header it authenticated with, so the audience the caller
    minted the token for is the service URL - which is what
    ``auth_expected_audience`` has to be set to.

    This duplicates a check Cloud Run IAM has already made, deliberately. IAM
    decides whether the request may enter; this decides whose name goes in the
    audit record, and a claim is only worth writing down if it was verified.
    """
    claims: dict[str, Any] = id_token.verify_oauth2_token(
        token, _TRANSPORT, audience=settings.auth_expected_audience
    )
    return claims


async def verify_auth_token(
    authorization: str | None = Header(None)
) -> str:
    """
    Authenticate the caller and return the identity to record in the audit log.

    Two paths, and only one of them is authentication:

    * ``auth_expected_audience`` set - the bearer credential is verified as a
      Google-signed ID token and the identity comes from the verified ``email``
      claim.
    * ``auth_expected_audience`` empty - local development. No verification is
      possible, so the returned identity is prefixed ``unverified-`` and says so
      in every log line it reaches. ``Settings`` refuses to construct in this
      state when ``ENVIRONMENT=production``, so it cannot reach a deployment.

    What this replaced accepted any bearer string of five characters or more and
    returned ``f"analyst-user-{token[:6]}"``. ``Bearer hunter2`` was logged as
    ``analyst-user-hunter``: not merely unauthenticated, but an audit trail that
    recorded an attacker-chosen name as though it were an identity.
    """
    token = _read_bearer_token(authorization)

    if not settings.auth_expected_audience:
        logger.warning(
            "auth_expected_audience is unset: bearer credential accepted without "
            "verification. This is a development-only path."
        )
        return f"unverified-dev-{token[:6]}"

    try:
        # verify_oauth2_token does blocking I/O when its certificate cache is
        # cold. Off the event loop, or one expired cache stalls every request
        # the worker is currently serving.
        claims = await run_in_threadpool(_verify_google_id_token, token)
    except (GoogleAuthError, ValueError) as exc:
        # The exception text names the failed claim - audience, expiry, issuer.
        # Useful in the log, not in the response: it tells an unauthenticated
        # caller exactly which value to change next.
        logger.warning("Bearer token rejected: %s", exc)
        raise HTTPException(
            status_code=401,
            detail="Bearer token failed verification."
        ) from exc

    # Google issues `email` on ID tokens for both users and service accounts.
    # `sub` is the fallback: stable and unique, just not human-readable.
    identity = claims.get("email") or claims.get("sub")
    if not identity:
        logger.warning("Verified token carried neither an email nor a sub claim.")
        raise HTTPException(
            status_code=401,
            detail="Bearer token failed verification."
        )

    return str(identity)
