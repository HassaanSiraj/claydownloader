"""FastAPI app: paste a link, dispatch a Celery download task, poll status, grab file."""
from __future__ import annotations

import os
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .celery_app import celery_app
from .downloader import is_supported
from .tasks import download_video

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
STATIC_DIR = os.path.join(BASE_DIR, "static")
FILE_TTL_SECONDS = 15 * 60  # delete downloaded files after 15 minutes

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app = FastAPI(title="Social Media Video Downloader")


class DownloadRequest(BaseModel):
    url: str


def _cleanup_old_files() -> None:
    """Best-effort TTL cleanup so the disk doesn't fill up."""
    now = time.time()
    for name in os.listdir(DOWNLOAD_DIR):
        path = os.path.join(DOWNLOAD_DIR, name)
        try:
            if now - os.path.getmtime(path) > FILE_TTL_SECONDS:
                os.remove(path)
        except OSError:
            pass


@app.post("/api/download")
def start_download(req: DownloadRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(400, "URL is required")
    if not is_supported(url):
        raise HTTPException(400, "Unsupported platform. Use Instagram, TikTok, or Facebook.")

    _cleanup_old_files()
    task = download_video.delay(url)  # hand the job to Celery/Redis
    return {"job_id": task.id}


@app.get("/api/status/{job_id}")
def status(job_id: str):
    result = celery_app.AsyncResult(job_id)
    state = result.state  # PENDING, STARTED, PROGRESS, SUCCESS, FAILURE

    if state == "SUCCESS":
        return {
            "id": job_id,
            "status": "done",
            "progress": 100.0,
            "title": (result.result or {}).get("title"),
            "error": None,
            "download_url": f"/api/file/{job_id}",
        }
    if state == "FAILURE":
        return {
            "id": job_id,
            "status": "error",
            "progress": 0.0,
            "title": None,
            "error": str(result.result),
            "download_url": None,
        }

    # PENDING (queued/unknown) / STARTED / PROGRESS
    progress = 0.0
    if state == "PROGRESS" and isinstance(result.info, dict):
        progress = result.info.get("progress", 0.0)
    return {
        "id": job_id,
        "status": "downloading" if state in ("STARTED", "PROGRESS") else "queued",
        "progress": progress,
        "title": None,
        "error": None,
        "download_url": None,
    }


@app.get("/api/file/{job_id}")
def get_file(job_id: str):
    result = celery_app.AsyncResult(job_id)
    if result.state != "SUCCESS":
        raise HTTPException(404, "File not ready")
    info = result.result or {}
    path = info.get("filepath")
    if not path or not os.path.exists(path):
        raise HTTPException(410, "File expired. Please download again.")
    title = info.get("title", "video")
    ext = os.path.splitext(path)[1].lstrip(".")
    return FileResponse(path, filename=f"{title}.{ext}", media_type="application/octet-stream")


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as f:
        return f.read()


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
