"""HireSignal FastAPI application factory."""

from __future__ import annotations

import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.core.config import get_settings
from backend.core.exceptions import HireSignalError
from backend.core.logging_config import setup_logging
from backend.api.health import router as health_router
from backend.resume.routes import router as resume_router
from backend.social.routes import router as social_router
from backend.synthesis.routes import router as synthesis_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI app instance.
    """
    settings = get_settings()
    setup_logging(level=logging.DEBUG if settings.DEBUG else logging.INFO)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Application lifespan handler."""
        logger.info(
            "Starting %s v%s in %s mode",
            settings.APP_NAME, settings.APP_VERSION, settings.ENVIRONMENT,
        )
        yield
        logger.info("Shutting down %s", settings.APP_NAME)

    app = FastAPI(
        title=settings.APP_NAME,
        description="""
# HireSignal - ATS with Social Media Intelligence

A complete Applicant Tracking System that combines resume parsing/scoring
with social media intelligence to provide comprehensive candidate evaluation.

## Modules

- **Resume Scoring** (`/api/v1/resume/*`): Parse and score resumes against job descriptions
- **Social Intelligence** (`/api/v1/social/*`): Analyze GitHub, LinkedIn, Twitter presence
- **Candidate Evaluation** (`/api/v1/candidate/*`): Combine scores into final report

## Authentication

All endpoints require an `X-API-Key` header. The default key is `dev-api-key-change-in-production`.

## Rate Limiting

100 requests per minute per API key.
        """,
        version=settings.APP_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception handler for custom exceptions
    @app.exception_handler(HireSignalError)
    async def hiresignal_exception_handler(request: Request, exc: HireSignalError) -> JSONResponse:
        """Handle custom HireSignal exceptions."""
        logger.warning(
            "Request to %s failed: %s (status=%d)",
            request.url.path, exc.message, exc.status_code,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.__class__.__name__,
                "message": exc.message,
                "status_code": exc.status_code,
            },
        )

    # Include routers
    app.include_router(health_router)
    app.include_router(resume_router)
    app.include_router(social_router)
    app.include_router(synthesis_router)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        """Root endpoint."""
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
        }

    return app


# Create the app instance for uvicorn
app = create_app()
