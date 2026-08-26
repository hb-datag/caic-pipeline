"""All tunable settings in one place.

Values can be overridden with environment variables (set via Modal secrets
or in the function definition) so behavior changes without code edits.
"""

import os

# ---------------------------------------------------------------------------
# LLM backend — THE config switch (see pipeline/llm.py).
#   "vllm"      any OpenAI-compatible server: currently Ollama on the CAIC
#               5090 workstation; also works with vLLM on Modal GPU, LM Studio…
#               (requires CAIC_VLLM_BASE_URL, normally set via the caic-llm secret)
#   "gemini"    Google Gemini free tier   (requires GEMINI_API_KEY in a secret)
#   "anthropic" Claude API — paid         (requires ANTHROPIC_API_KEY in a secret)
# ---------------------------------------------------------------------------
LLM_BACKEND = os.environ.get("CAIC_LLM_BACKEND", "vllm")

# Model per backend (validated at the Phase 2 quality checkpoint).
VLLM_MODEL = os.environ.get("CAIC_VLLM_MODEL", "qwen3.6:27b")  # Ollama tag
GEMINI_MODEL = os.environ.get("CAIC_GEMINI_MODEL", "gemini-2.5-flash")
ANTHROPIC_MODEL = os.environ.get("CAIC_ANTHROPIC_MODEL", "claude-sonnet-5")

# The OpenAI-compatible server URL (Tailscale Funnel to the 5090, SETUP.md §7).
VLLM_BASE_URL = os.environ.get("CAIC_VLLM_BASE_URL", "").rstrip("/")

# Whisper service (Phase 3) — same funnel host as the LLM, /whisper path.
WHISPER_BASE_URL = os.environ.get(
    "CAIC_WHISPER_BASE_URL",
    (VLLM_BASE_URL + "/whisper") if VLLM_BASE_URL else "")

# Shown to the operator when the LLM machine is unreachable.
OFFLINE_MESSAGE = os.environ.get(
    "CAIC_OFFLINE_MESSAGE",
    "Please contact Haidar at 419-324-5282 if you are seeing this message.")

# Site publishing (Phase 2)
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")     # e.g. "youruser/caic-pipeline"
SITE_BRANCH = os.environ.get("CAIC_SITE_BRANCH", "main")
SITE_DIR = "docs"  # GitHub Pages serves from /docs on main

# CAIC brand palette (sampled from cincinnatiaicatalyst.org) — used by the
# branded slide (Phase 4) and site templates (Phase 2).
BRAND = {
    "blue": "#1b5a7d",       # primary
    "navy": "#0f3a54",       # deep
    "blue_soft": "#2d6f94",
    "accent": "#6aa9cc",     # light-blue accent
    "bg": "#dfe6eb",         # light blue-gray
    "ink": "#22333c",
    "font": "Montserrat",
}

# Video (Phase 4) — inputs matching this profile take the stream-copy fast path.
TARGET_VIDEO = {"width": 1920, "height": 1080, "fps": 30,
                "vcodec": "h264", "acodec": "aac"}
