"""Thin wrapper around yt-dlp. This is where the actual downloading happens."""
from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass

import yt_dlp

log = logging.getLogger("downloader")

# Hosts we advertise as supported. yt-dlp handles far more, but we gate the UI
# to keep expectations honest for the MVP.
SUPPORTED_HOSTS = (
    "instagram.com",
    "tiktok.com",
    "facebook.com",
    "fb.watch",
)


@dataclass
class DownloadResult:
    filepath: str
    title: str
    ext: str


def is_supported(url: str) -> bool:
    url = url.lower()
    return any(host in url for host in SUPPORTED_HOSTS)


def _video_codec(filepath: str) -> str | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name", "-of", "json", filepath],
            capture_output=True, text=True, check=True,
        )
        return json.loads(out.stdout)["streams"][0]["codec_name"]
    except Exception:
        log.warning("ffprobe failed on %s", filepath, exc_info=True)
        return None


def _ensure_compatible(filepath: str) -> None:
    """Re-encode to H.264/AAC in place if the source codec (e.g. VP9/AV1,
    which some platforms serve with no H.264 alternative) isn't the
    H.264/AAC combo that WhatsApp and most mobile/native players expect.
    """
    if _video_codec(filepath) == "h264":
        return
    log.warning("transcoding %s to H.264 for player compatibility", filepath)
    fixed = filepath + ".fixed.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-i", filepath,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-c:a", "aac", "-b:a", "128k",
         "-movflags", "+faststart", fixed],
        check=True, capture_output=True,
    )
    os.replace(fixed, filepath)


def download(url: str, out_dir: str, progress_hook=None) -> DownloadResult:
    """Download the best-quality video+audio to out_dir and return the file path.

    progress_hook: optional callable receiving yt-dlp's progress dict so the
    caller can surface percentage/status to the user.
    """
    os.makedirs(out_dir, exist_ok=True)

    opts = {
        # Prefer H.264/AAC — the combo nearly every player (WhatsApp, iOS,
        # Android, etc.) supports. Unconstrained "bestvideo+bestaudio" can
        # pick VP9/AV1/Opus streams that only permissive players like VLC
        # decode, even though ffmpeg happily remuxes them into an .mp4.
        "format": (
            "bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]"
            "/best[vcodec^=avc1][acodec^=mp4a]"
            "/bestvideo+bestaudio/best"
        ),
        "outtmpl": os.path.join(out_dir, "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        # moov atom at the front so players can start/scan without
        # buffering the whole file first (required by some mobile players).
        "postprocessor_args": {"default": ["-movflags", "+faststart"]},
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
    }
    if progress_hook:
        opts["progress_hooks"] = [progress_hook]

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filepath = ydl.prepare_filename(info)
        # merge_output_format may rewrite the extension to .mp4
        if not os.path.exists(filepath):
            base = os.path.splitext(filepath)[0]
            filepath = base + ".mp4"
        _ensure_compatible(filepath)
        return DownloadResult(
            filepath=filepath,
            title=info.get("title", "video"),
            ext=os.path.splitext(filepath)[1].lstrip("."),
        )
