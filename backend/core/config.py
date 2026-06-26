"""Application configuration and environment variables."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    APP_NAME: str = "HireSignal"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"

    # API Keys
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_SITE_URL: str = ""
    OPENROUTER_APP_NAME: str = "HireSignal"
    ANTHROPIC_API_KEY: Optional[str] = None

    # Public developer profile APIs (optional)
    GITHUB_TOKEN: Optional[str] = None
    HUGGINGFACE_TOKEN: Optional[str] = None
    BRAVE_SEARCH_API_KEY: Optional[str] = None
    FIRECRAWL_API_KEY: Optional[str] = None
    WEB_DISCOVERY_ENABLED: bool = True
    WEB_DISCOVERY_MAX_QUERIES: int = 6
    WEB_DISCOVERY_MAX_RESULTS: int = 5
    FIRECRAWL_ENABLED: bool = True
    FIRECRAWL_MAX_PAGES: int = 5

    # LinkedIn / Twitter (optional)
    LINKEDIN_API_KEY: Optional[str] = None
    LINKEDIN_CLIENT_SECRET: Optional[str] = None
    TWITTER_API_KEY: Optional[str] = None
    TWITTER_API_SECRET: Optional[str] = None
    TWITTER_BEARER_TOKEN: Optional[str] = None

    # Internal API Key for endpoint auth
    API_KEY: str = "dev-api-key-change-in-production"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Qdrant
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_COLLECTION_NAME: str = "hiresignal_skills"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # Rate limiting
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 100

    # Scoring weights
    RESUME_WEIGHT: float = 0.60
    SOCIAL_WEIGHT: float = 0.40

    # Cache TTL
    CACHE_TTL_SECONDS: int = 86400  # 24 hours

    # File upload
    MAX_UPLOAD_SIZE_MB: int = 10
    ALLOWED_RESUME_EXTENSIONS: set[str] = {".pdf", ".docx"}

    # LLM
    LLM_PROVIDER: str = "openai"
    LLM_MODEL: str = "gpt-4o-mini"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    LLM_FALLBACK_ENABLED: bool = True


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
