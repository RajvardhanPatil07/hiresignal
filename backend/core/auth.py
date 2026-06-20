"""API key authentication for HireSignal endpoints."""

from __future__ import annotations

from fastapi import Security, status
from fastapi.security import APIKeyHeader

from backend.core.config import get_settings
from backend.core.exceptions import AuthenticationError

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Verify the provided API key against the configured key.

    Args:
        api_key: The API key from the X-API-Key header.

    Returns:
        The validated API key string.

    Raises:
        AuthenticationError: If the API key is missing or invalid.
    """
    settings = get_settings()
    if not api_key:
        raise AuthenticationError("Missing API key. Provide it in the X-API-Key header.")
    if api_key != settings.API_KEY:
        raise AuthenticationError("Invalid API key.")
    return api_key
