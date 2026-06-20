"""Configuration helpers for OpenAI-compatible AI providers."""

from __future__ import annotations

from typing import Any


def _provider(settings: Any) -> str:
    """Return a supported provider name, including for loosely mocked settings."""
    value = getattr(settings, "LLM_PROVIDER", "openai")
    if not isinstance(value, str):
        return "openai"
    return value.strip().lower()


def api_key(settings: Any) -> str:
    """Return the API key for the selected provider."""
    if _provider(settings) == "openrouter":
        value = getattr(settings, "OPENROUTER_API_KEY", "")
    else:
        value = getattr(settings, "OPENAI_API_KEY", "")
    return value if isinstance(value, str) else ""


def api_base_url(settings: Any) -> str:
    """Return the selected provider's OpenAI-compatible API base URL."""
    if _provider(settings) == "openrouter":
        value = getattr(settings, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        default = "https://openrouter.ai/api/v1"
    else:
        value = getattr(settings, "OPENAI_BASE_URL", "https://api.openai.com/v1")
        default = "https://api.openai.com/v1"
    return (value if isinstance(value, str) and value else default).rstrip("/")


def api_headers(settings: Any) -> dict[str, str]:
    """Build authentication and optional OpenRouter attribution headers."""
    headers = {
        "Authorization": f"Bearer {api_key(settings)}",
        "Content-Type": "application/json",
    }
    if _provider(settings) == "openrouter":
        site_url = getattr(settings, "OPENROUTER_SITE_URL", "")
        app_name = getattr(settings, "OPENROUTER_APP_NAME", "HireSignal")
        if isinstance(site_url, str) and site_url:
            headers["HTTP-Referer"] = site_url
        if isinstance(app_name, str) and app_name:
            headers["X-Title"] = app_name
    return headers
