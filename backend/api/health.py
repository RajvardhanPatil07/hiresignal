"""Health check endpoints for HireSignal."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, status

from backend.core.cache import get_redis, close_redis
from backend.core.config import get_settings
from backend.models.schemas import HealthStatus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthStatus,
    status_code=status.HTTP_200_OK,
    summary="System health check",
    description="Check the health of all HireSignal services.",
)
async def health_check() -> HealthStatus:
    """Check system health.

    Returns:
        HealthStatus with individual service statuses.
    """
    settings = get_settings()
    services: dict[str, str] = {}

    # Check Redis
    try:
        redis_client = await get_redis()
        await redis_client.ping()
        services["redis"] = "healthy"
    except Exception as exc:
        logger.warning("Redis health check failed: %s", exc)
        services["redis"] = "unhealthy"

    # Check Qdrant (optional)
    try:
        services["qdrant"] = "healthy (dev mode)"
    except Exception as exc:
        services["qdrant"] = f"unhealthy: {exc}"

    # Overall status
    overall = "healthy"
    if services.get("redis") == "unhealthy":
        overall = "degraded"

    return HealthStatus(
        status=overall,
        version=settings.APP_VERSION,
        services=services,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/health/ready",
    status_code=status.HTTP_200_OK,
    summary="Readiness probe",
)
async def readiness_probe() -> dict[str, str]:
    """Kubernetes-style readiness probe."""
    return {"status": "ready"}


@router.get(
    "/health/live",
    status_code=status.HTTP_200_OK,
    summary="Liveness probe",
)
async def liveness_probe() -> dict[str, str]:
    """Kubernetes-style liveness probe."""
    return {"status": "alive"}
