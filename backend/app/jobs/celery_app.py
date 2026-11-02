"""Jobbkö (SPEC 3: alla steg körs som asynkrona jobb). Tasks per pipeline-steg läggs till i senare faser."""

from __future__ import annotations

from celery import Celery

from app.config.settings import get_settings

celery_app = Celery("vs_kalkyl", broker=get_settings().redis_url, backend=get_settings().redis_url)
celery_app.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, task_serializer="json")
