"""CAIC whisper service - runs on the CAIC 5090 workstation next to Ollama.

Tiny FastAPI app around faster-whisper. The pipeline sends extracted meeting
audio here and gets back segments with word-level timestamps.

Exposed through the same Tailscale Funnel as Ollama, mounted at /whisper
(routes are registered both with and without the prefix, so it works whether
or not the proxy strips it).

Auth: requests must carry "Authorization: Bearer <CAIC_WHISPER_KEY>".
The launcher script sets that env var; it is never stored in this repo.

Run (see guides/SETUP.md section 9):
    uvicorn api:app --host 127.0.0.1 --port 8001
"""

import os
import tempfile

from fastapi import APIRouter, FastAPI, File, Header, HTTPException, UploadFile

MODEL_NAME = os.environ.get("CAIC_WHISPER_MODEL", "large-v3-turbo")
API_KEY = os.environ.get("CAIC_WHISPER_KEY", "")

app = FastAPI(title="CAIC whisper")
router = APIRouter()

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        try:
            _model = WhisperModel(MODEL_NAME, device="cuda", compute_type="float16")
            print(f"whisper: {MODEL_NAME} on CUDA")
        except Exception as exc:  # noqa: BLE001 - CPU fallback keeps us alive
            print(f"whisper: CUDA init failed ({exc}); falling back to CPU int8")
            _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
    return _model


@router.get("/health")
def health():
    return {"ok": True, "model": MODEL_NAME}


@router.post("/transcribe")
async def transcribe(audio: UploadFile = File(...), authorization: str = Header("")):
    if not API_KEY or authorization != f"Bearer {API_KEY}":
        raise HTTPException(401, "bad or missing key")

    suffix = os.path.splitext(audio.filename or "audio.mp3")[1] or ".mp3"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await audio.read())
        path = tmp.name

    try:
        segments, info = _get_model().transcribe(
            path, word_timestamps=True, vad_filter=True)
        out = []
        for seg in segments:
            out.append({
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "text": seg.text.strip(),
                "words": [{"w": w.word, "start": round(w.start, 2),
                           "end": round(w.end, 2)} for w in (seg.words or [])],
            })
        return {"language": info.language,
                "duration": round(info.duration, 2),
                "segments": out}
    finally:
        os.unlink(path)


# Mounted with and without the /whisper prefix (see module docstring).
app.include_router(router)
app.include_router(router, prefix="/whisper")
