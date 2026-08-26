"""Phase 3: video -> audio -> transcript via the whisper service on the 5090.

Steps:
  1. ffmpeg extracts mono 16 kHz audio (small enough to send over the funnel)
  2. POST it to the whisper service (faster-whisper, word-level timestamps)
  3. Save two artifacts next to the video:
       transcript.txt   "[HH:MM:SS] text" per segment — what the LLM reads,
                        so key points and chapters get real timestamps
       transcript.json  full segments + word timings (audit + Phase 4 use)
"""

import json
import subprocess
import time
from pathlib import Path

import requests

from . import config
from .llm import LLMError


def _hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _headers() -> dict:
    import os
    return {"Authorization": f"Bearer {os.environ.get('CAIC_PASSCODE', '')}"}


def ensure_whisper_ready(log=print, timeout_s: int = 600) -> None:
    if not config.WHISPER_BASE_URL:
        raise LLMError("Whisper URL not configured. " + config.OFFLINE_MESSAGE)
    start = time.time()
    while time.time() - start < timeout_s:
        detail = ""
        try:
            r = requests.get(f"{config.WHISPER_BASE_URL}/health", timeout=15)
            if r.status_code == 200:
                return
            detail = f"HTTP {r.status_code}"
        except requests.RequestException as exc:
            detail = exc.__class__.__name__
        log(f"whisper server not ready ({detail}) — retrying…")
        time.sleep(15)
    raise LLMError("The transcription server is not reachable. "
                   + config.OFFLINE_MESSAGE)


def extract_audio(video_path: str, log=print) -> Path:
    audio = Path(video_path).with_name("audio.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000",
         "-b:a", "48k", str(audio)],
        check=True, capture_output=True)
    log(f"Audio extracted: {audio.stat().st_size / 1e6:.1f} MB")
    return audio


def transcribe_video(video_path: str, log=print) -> Path:
    """Full step: returns the path of the generated transcript.txt."""
    audio = extract_audio(video_path, log=log)

    ensure_whisper_ready(log=log)
    log("Transcribing on the whisper server (roughly 2-5 min per meeting hour)…")
    with audio.open("rb") as f:
        resp = requests.post(
            f"{config.WHISPER_BASE_URL}/transcribe",
            files={"audio": ("audio.mp3", f, "audio/mpeg")},
            headers=_headers(),
            timeout=60 * 60,
        )
    if resp.status_code != 200:
        raise LLMError(f"Transcription failed (HTTP {resp.status_code}: "
                       f"{resp.text[:200]})")
    data = resp.json()

    jobdir = Path(video_path).parent
    (jobdir / "transcript.json").write_text(
        json.dumps(data, indent=1), encoding="utf-8")

    lines = [f"[{_hms(s['start'])}] {s['text']}" for s in data["segments"]]
    txt = jobdir / "transcript.txt"
    txt.write_text("\n".join(lines), encoding="utf-8")

    log(f"Transcribed {_hms(data.get('duration', 0))} of audio "
        f"({len(data['segments'])} segments, language: {data.get('language')})")
    return txt
