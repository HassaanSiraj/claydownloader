"""Thin wrapper around yt-dlp. This is where the actual downloading happens."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import yt_dlp

log = logging.getLogger("downloader")

# Default browser to pull cookies from when COOKIES_FROM_BROWSER is unset.
DEFAULT_BROWSER = "chrome"

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


def _apply_cookies(opts: dict) -> None:
    """Attach cookies so age/bot-gated sites work.

    Two ways, controlled by env vars:
      COOKIES_FROM_BROWSER=chrome|safari|firefox|edge|brave  -> read live
          cookies straight from that browser's profile (best for local use).
      COOKIES_FILE=/path/to/cookies.txt                      -> Netscape-format
          cookie file (best for servers, where no browser is installed).
    """
    cookie_file = os.environ.get("COOKIES_FILE")
    browser = os.environ.get("COOKIES_FROM_BROWSER", DEFAULT_BROWSER)

    # A cookies.txt file is the most robust option (no Keychain, fork-safe),
    # so prefer it when provided.
    if cookie_file and os.path.exists(cookie_file):
        opts["cookiefile"] = cookie_file
        log.warning("cookies: using file %s", cookie_file)
    elif browser:
        # yt-dlp expects a tuple: (browser_name, profile, keyring, container)
        opts["cookiesfrombrowser"] = (browser.strip().lower(),)
        log.warning("cookies: using browser %s", browser)
    else:
        log.warning("cookies: NONE")


def download(url: str, out_dir: str, progress_hook=None) -> DownloadResult:
    """Download the best-quality video+audio to out_dir and return the file path.

    progress_hook: optional callable receiving yt-dlp's progress dict so the
    caller can surface percentage/status to the user.
    """
    os.makedirs(out_dir, exist_ok=True)

    opts = {
        # bestvideo+bestaudio needs ffmpeg to merge; falls back to a single
        # progressive stream if merging isn't possible.
        "format": "bestvideo+bestaudio/best",
        "outtmpl": os.path.join(out_dir, "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
    }
    _apply_cookies(opts)
    if progress_hook:
        opts["progress_hooks"] = [progress_hook]

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filepath = ydl.prepare_filename(info)
        # merge_output_format may rewrite the extension to .mp4
        if not os.path.exists(filepath):
            base = os.path.splitext(filepath)[0]
            filepath = base + ".mp4"
        return DownloadResult(
            filepath=filepath,
            title=info.get("title", "video"),
            ext=os.path.splitext(filepath)[1].lstrip("."),
        )
