"""Celery task that runs the download in a worker process.

Progress is reported via Celery custom state (update_state), which the API
reads back through AsyncResult. This replaces the old in-memory job dict —
state now lives in Redis, so multiple workers and API processes share it.
"""
from __future__ import annotations

import os

from .celery_app import celery_app
from .downloader import DownloadResult, download

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")


@celery_app.task(bind=True, name="download_video")
def download_video(self, url: str) -> dict:
    """Download `url` and return {filepath, title}. Raises on failure."""
    def hook(d: dict) -> None:
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            pct = round(done / total * 100, 1) if total else 0.0
            self.update_state(state="PROGRESS", meta={"progress": pct})

    result: DownloadResult = download(url, DOWNLOAD_DIR, progress_hook=hook)
    return {"filepath": result.filepath, "title": result.title}
