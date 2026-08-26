"""CAIC Video Pipeline — Modal entrypoint.

One codebase, all cloud, no servers to manage.

    modal deploy modal_app.py   # deploy / update everything
    modal serve modal_app.py    # dev mode with live reload

Pieces defined here:
  * web()         — the operator upload page + RUN endpoint + status feed (FastAPI)
  * process_job() — the background job, spawned per RUN click

Requires the Modal secret `caic-app` (key: CAIC_PASSCODE). See guides/SETUP.md.
"""

import modal

APP_NAME = "caic-pipeline"

app = modal.App(APP_NAME)

# Lightweight image for the web app and CPU pipeline stages.
# (GPU images for whisper/vLLM come in Phases 2-3 and are separate,
#  so the web app stays fast and cheap.)
cpu_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg", "fonts-dejavu")  # stitch (Phase 4) + slide fonts
    .pip_install(
        "fastapi[standard]~=0.115",
        "jinja2~=3.1",
        "jsonschema~=4.23",
        "requests~=2.32",
        "pillow~=11.0",
    )
    .add_local_dir("web", remote_path="/root/web")
    .add_local_dir("site_templates", remote_path="/root/site_templates")
    .add_local_dir("assets", remote_path="/root/assets")
    .add_local_python_source("pipeline")
)

# Persistent storage shared by all functions: uploads + intermediate artifacts.
data_vol = modal.Volume.from_name("caic-data", create_if_missing=True)
# Hugging Face model cache — so the 27GB model downloads once, not per boot.
hf_cache = modal.Volume.from_name("caic-hf-cache", create_if_missing=True)

VOLUME_MOUNT = "/data"
VLLM_PORT = 8000

# ---------------------------------------------------------------------------
# LLM server: the pipeline talks to ANY OpenAI-compatible endpoint, configured
# by the `caic-llm` Modal secret (CAIC_VLLM_BASE_URL + CAIC_VLLM_MODEL).
#
# CURRENT SETUP: Ollama on Haidar's always-on RTX 5090 workstation, reachable
# through a Tailscale Funnel URL (see guides/SETUP.md §7). If the machine is
# offline, runs fail with a clear contact message in the status feed.
#
# ALTERNATIVE (the original all-cloud design, for a successor org without a
# GPU box): a vLLM server on a Modal GPU container. Modal requires a payment
# method on file for GPU functions (usage still draws from the free credit
# first). To use it: uncomment the function below, redeploy, and point
# CAIC_VLLM_BASE_URL at its printed URL.
#
# vllm_image = (
#     modal.Image.debian_slim(python_version="3.12")
#     .pip_install("vllm", "huggingface_hub[hf_transfer]")
#     .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
# )
#
# @app.function(
#     image=vllm_image,
#     gpu="L40S",  # 48 GB — fits Qwen3.6-27B-FP8 comfortably
#     volumes={"/root/.cache/huggingface": hf_cache},
#     secrets=[modal.Secret.from_name("caic-app")],
#     timeout=60 * 60,
#     scaledown_window=300,  # shut down after 5 idle minutes
#     max_containers=1,
# )
# @modal.concurrent(max_inputs=8)
# @modal.web_server(port=VLLM_PORT, startup_timeout=30 * 60)
# def vllm_server():
#     import os, subprocess
#     subprocess.Popen([
#         "vllm", "serve", os.environ.get("CAIC_VLLM_MODEL", "Qwen/Qwen3.6-27B-FP8"),
#         "--port", str(VLLM_PORT),
#         "--max-model-len", "65536",
#         "--api-key", os.environ["CAIC_PASSCODE"],
#     ])
# ---------------------------------------------------------------------------


@app.function(
    image=cpu_image,
    volumes={VOLUME_MOUNT: data_vol},
    secrets=[
        modal.Secret.from_name("caic-app"),
        modal.Secret.from_name("caic-github"),  # GITHUB_TOKEN + GITHUB_REPO
        modal.Secret.from_name("caic-llm"),     # CAIC_VLLM_BASE_URL + CAIC_VLLM_MODEL
    ],
    timeout=2 * 60 * 60,  # re-encode fallback on a long meeting needs headroom
)
def process_job(job_id: str) -> None:
    """Background job runner. Spawned (fire-and-forget) by the RUN endpoint."""
    # A reused (warm) container sees a stale volume snapshot — refresh it so
    # the files the web endpoint just committed are visible.
    data_vol.reload()

    from pipeline.runner import run_job

    try:
        run_job(job_id)
    finally:
        # Persist artifacts (final.mp4, youtube.txt, transcripts) so the
        # web endpoint can serve them for download.
        data_vol.commit()


@app.function(
    image=cpu_image,
    volumes={VOLUME_MOUNT: data_vol},
    secrets=[modal.Secret.from_name("caic-app")],
)
@modal.asgi_app()
def web():
    """The operator web app: upload page, RUN endpoint, status feed."""
    import hmac
    import os
    import re
    import shutil
    import uuid
    from pathlib import Path

    from fastapi import FastAPI, File, Form, HTTPException, UploadFile
    from fastapi.responses import FileResponse

    from pipeline import status as st

    api = FastAPI(title="CAIC Pipeline")

    # ---- passcode gate -------------------------------------------------
    def check_passcode(passcode: str) -> None:
        expected = os.environ.get("CAIC_PASSCODE", "")
        if not expected:
            raise HTTPException(500, "Server misconfigured: CAIC_PASSCODE not set")
        if not hmac.compare_digest(passcode or "", expected):
            raise HTTPException(401, "Wrong passcode")

    # ---- routes --------------------------------------------------------
    @api.get("/")
    def index():
        return FileResponse("/root/web/index.html")

    @api.get("/api/ping")
    def ping(passcode: str = ""):
        """Lets the page verify the passcode before showing the form."""
        check_passcode(passcode)
        return {"ok": True}

    @api.post("/api/run")
    async def run(
        passcode: str = Form(...),
        title: str = Form(...),
        date: str = Form(...),  # YYYY-MM-DD
        transcript_text: str = Form(""),
        video: UploadFile | None = File(None),
        transcript_file: UploadFile | None = File(None),
    ):
        check_passcode(passcode)

        title = title.strip()
        if not title:
            raise HTTPException(400, "Title is required")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise HTTPException(400, "Date must be YYYY-MM-DD")

        has_video = video is not None and video.filename
        has_transcript = bool(transcript_text.strip()) or (
            transcript_file is not None and transcript_file.filename
        )
        if not has_video and not has_transcript:
            raise HTTPException(400, "Upload a video, a transcript, or both")

        # Job id: date + slug + short random suffix, e.g. 2026-08-23-board-sync-a1b2c3
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "meeting"
        job_id = f"{date}-{slug}-{uuid.uuid4().hex[:6]}"

        job_dir = Path(VOLUME_MOUNT) / "jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        inputs = {"video": None, "transcript": None}

        if has_video:
            ext = Path(video.filename).suffix.lower() or ".mp4"
            dest = job_dir / f"input_video{ext}"
            with dest.open("wb") as f:
                shutil.copyfileobj(video.file, f)
            inputs["video"] = str(dest)

        if has_transcript:
            dest = job_dir / "transcript.txt"
            if transcript_text.strip():
                dest.write_text(transcript_text, encoding="utf-8")
            else:
                with dest.open("wb") as f:
                    shutil.copyfileobj(transcript_file.file, f)
            inputs["transcript"] = str(dest)

        data_vol.commit()  # make files visible to the worker container

        st.create_job(job_id, title, date, inputs)
        process_job.spawn(job_id)
        return {"job_id": job_id}

    @api.get("/api/status/{job_id}")
    def get_status(job_id: str, passcode: str = ""):
        check_passcode(passcode)
        job = st.get(job_id)
        if job is None:
            raise HTTPException(404, "Unknown job")
        return job

    @api.get("/api/jobs")
    def recent_jobs(passcode: str = ""):
        check_passcode(passcode)
        return {"jobs": st.recent()}

    # Downloadable artifacts (Phase 4): only these exact names are served.
    _DOWNLOADS = {"final.mp4": "assembly/final.mp4",
                  "youtube.txt": "youtube.txt",
                  "transcript.txt": "transcript.txt"}

    @api.get("/api/download/{job_id}/{name}")
    def download(job_id: str, name: str, passcode: str = ""):
        check_passcode(passcode)
        rel = _DOWNLOADS.get(name)
        if rel is None or "/" in job_id or ".." in job_id:
            raise HTTPException(404, "unknown file")
        data_vol.reload()  # see the worker's latest commit
        path = Path(VOLUME_MOUNT) / "jobs" / job_id / rel
        if not path.exists():
            raise HTTPException(404, "not found (job may still be running)")
        return FileResponse(str(path), filename=f"{job_id}-{name}")

    return api
