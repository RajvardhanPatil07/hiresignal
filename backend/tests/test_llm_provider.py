"""Tests for OpenAI-compatible provider configuration."""

from types import SimpleNamespace

from backend.core.llm_provider import api_base_url, api_headers, api_key


def test_openai_defaults() -> None:
    settings = SimpleNamespace(LLM_PROVIDER="openai", OPENAI_API_KEY="openai-key")

    assert api_key(settings) == "openai-key"
    assert api_base_url(settings) == "https://api.openai.com/v1"
    assert api_headers(settings)["Authorization"] == "Bearer openai-key"


def test_openrouter_configuration() -> None:
    settings = SimpleNamespace(
        LLM_PROVIDER="openrouter",
        OPENROUTER_API_KEY="router-key",
        OPENROUTER_BASE_URL="https://openrouter.ai/api/v1/",
        OPENROUTER_SITE_URL="https://hiresignal.example",
        OPENROUTER_APP_NAME="HireSignal Custom",
    )

    assert api_key(settings) == "router-key"
    assert api_base_url(settings) == "https://openrouter.ai/api/v1"
    assert api_headers(settings) == {
        "Authorization": "Bearer router-key",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://hiresignal.example",
        "X-Title": "HireSignal Custom",
    }
