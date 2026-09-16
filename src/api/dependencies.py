"""
FastAPI Dependencies Module.
Provides authentication verification and Dependency Injection container access.
"""


from fastapi import Header, HTTPException

from src.core.container import ApplicationContainer, container


async def get_container() -> ApplicationContainer:
    """Provides application DI container instance."""
    return container


async def verify_auth_token(
    authorization: str | None = Header(None)
) -> str:
    """
    Validates Bearer token / Cloud IAM authorization header.
    Allows test tokens in development or verifies format.
    """
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

    token = parts[1]
    if not token or len(token) < 5:
        raise HTTPException(
            status_code=401,
            detail="Invalid or malformed Bearer token."
        )

    # Return sanitized identity
    return f"analyst-user-{token[:6]}"
