"""Celery application. Redis is both the broker (job inbox) and result backend."""
from __future__ import annotations

import os

from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "downloader",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    result_expires=3600,          # forget results after 1h
    worker_max_tasks_per_child=50,  # recycle workers to bound memory/leaks
    broker_connection_retry_on_startup=True,
)
