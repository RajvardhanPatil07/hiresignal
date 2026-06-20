"""Celery application configuration for HireSignal."""

from __future__ import annotations

from celery import Celery

from backend.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "hiresignal",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "backend.social.agents",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes max per task
    worker_prefetch_multiplier=1,
)

# Auto-discover tasks
celery_app.autodiscover_tasks()


@celery_app.task(bind=True)
def debug_task(self) -> str:
    """Debug task to verify Celery is working."""
    return f"Request: {self.request!r}"
