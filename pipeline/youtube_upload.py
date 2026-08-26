"""YouTube auto-upload (upload-as-private) — DORMANT until the API audit passes.

WHY DORMANT: YouTube locks any video uploaded through an unverified API
project to private permanently (it can never be published). Until the CAIC
Google Cloud project passes YouTube's compliance audit, this stays off and
the operator uploads the YouTube Kit manually (~2 min).

TO ENABLE (after the audit — see guides/REDEPLOY.md):
  1. Create the Modal secret:
       modal secret create caic-youtube YT_CLIENT_ID=... YT_CLIENT_SECRET=... \
           YT_REFRESH_TOKEN=... CAIC_YOUTUBE_UPLOAD=on
  2. In modal_app.py, uncomment the caic-youtube secret on process_job.
  3. Redeploy. Videos then upload as PRIVATE with metadata pre-filled;
     the operator just clicks Publish in YouTube Studio.

Uses plain HTTPS (no Google SDK): refresh-token -> access-token, then a
resumable upload session.
"""

import json
import os
from pathlib import Path

import requests

from . import config


def enabled() -> bool:
    return config.YOUTUBE_UPLOAD == "on" and bool(os.environ.get("YT_REFRESH_TOKEN"))


def _access_token() -> str:
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": os.environ["YT_CLIENT_ID"],
        "client_secret": os.environ["YT_CLIENT_SECRET"],
        "refresh_token": os.environ["YT_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }, timeout=60)
    r.raise_for_status()
    return r.json()["access_token"]


def upload_private(video_path: str, title: str, description: str,
                   log=print) -> str:
    """Upload as private. Returns the watch URL."""
    token = _access_token()
    meta = {
        "snippet": {"title": title[:100], "description": description[:4900],
                    "categoryId": "28"},  # Science & Technology
        "status": {"privacyStatus": "private",
                   "selfDeclaredMadeForKids": False},
    }
    size = Path(video_path).stat().st_size
    start = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos"
        "?uploadType=resumable&part=snippet,status",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json",
                 "X-Upload-Content-Type": "video/mp4",
                 "X-Upload-Content-Length": str(size)},
        data=json.dumps(meta), timeout=60)
    start.raise_for_status()
    session_url = start.headers["Location"]

    log(f"Uploading {size / 1e9:.2f} GB to YouTube (private)…")
    with open(video_path, "rb") as f:
        done = requests.put(session_url,
                            headers={"Authorization": f"Bearer {token}",
                                     "Content-Type": "video/mp4"},
                            data=f, timeout=60 * 60)
    done.raise_for_status()
    vid = done.json()["id"]
    return f"https://www.youtube.com/watch?v={vid}"
