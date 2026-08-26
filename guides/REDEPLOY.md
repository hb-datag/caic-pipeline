# Successor Redeploy Guide

Everything a successor org needs to run this pipeline from their own
accounts. Total time from zero: roughly an afternoon.

## What this system is (30 seconds)

* **Modal** hosts the operator web page and the processing jobs (free tier).
* **A GPU workstation you control** serves the two AI models via **Ollama**
  (analysis, Qwen3.6-27B) and **faster-whisper** (transcription), exposed
  to Modal through a **Tailscale Funnel** URL. Alternative without a GPU box:
  uncomment the vLLM function in `modal_app.py` and run the LLM on a Modal
  GPU (requires a payment method on file; usage draws from free credit).
  Or set `CAIC_LLM_BACKEND=gemini` + `GEMINI_API_KEY` for the Gemini free tier.
* **GitHub** stores the code, the concept ledger (`data/concepts.json`),
  and serves the public site from `docs/` via GitHub Pages.

## Accounts needed

| Account | Used for | Cost |
|---|---|---|
| Modal | web app + jobs | free tier |
| GitHub | repo + public site (repo must be public) | free |
| Tailscale | funnel to the GPU box | free plan |
| Google (org account) | YouTube channel; API audit for auto-upload | free |
| Domain registrar | custom domain (optional) | domain cost |

## Steps

1. **Fork/clone the repo** to your org's GitHub account (public).
2. **Modal:** `pip install modal`, `modal setup`, then create secrets:
   * `caic-app` — `CAIC_PASSCODE=<shared passcode>`
   * `caic-github` — `GITHUB_TOKEN=<fine-grained token, Contents R/W on this
     repo only>`, `GITHUB_REPO=<owner>/<repo>`
   * `caic-llm` — `CAIC_VLLM_BASE_URL=<funnel url>`, `CAIC_VLLM_MODEL=qwen3.6:27b`
3. **GPU workstation** (Windows; ~32 GB VRAM recommended):
   * Install Ollama; `ollama pull qwen3.6:27b`; set env vars
     `OLLAMA_HOST=0.0.0.0`, `OLLAMA_ORIGINS=*`, `OLLAMA_CONTEXT_LENGTH=40960`,
     `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`,
     `OLLAMA_KEEP_ALIVE=30m`; restart Ollama.
   * Whisper service: create a Python 3.12 venv, `pip install -r
     whisper_service/requirements.txt`, run
     `uvicorn api:app --host 127.0.0.1 --port 8001` from `whisper_service/`
     with `CAIC_WHISPER_KEY=<passcode>` set; add the launcher to the Startup
     folder (see `scratch/setup_whisper.bat` pattern in SETUP.md §7/§9).
   * Tailscale: sign in, then `tailscale funnel --bg 11434` and
     `tailscale funnel --bg --set-path=/whisper 8001`.
4. **Deploy:** `modal deploy modal_app.py` from the repo folder.
5. **GitHub Pages:** repo Settings → Pages → deploy from branch → `main`,
   `/docs`. Custom domain optional: add a CNAME record
   (`<sub>.yourdomain.com` → `<owner>.github.io`), set it in the Pages
   settings, enable Enforce HTTPS, and set `CAIC_PAGES_URL` in
   `pipeline/config.py` (or env) to the new URL.
6. **Update identity:** `pipeline/config.py` (`OFFLINE_MESSAGE`, `PAGES_URL`,
   brand palette if desired) and the operator URL in `guides/RUNBOOK.md`.
7. **Test:** paste any transcript into the upload page; a summary page must
   appear on the public site within ~3 minutes.

## YouTube auto-upload (optional, post-audit)

Without it, operators upload the YouTube Kit manually (~2 min) — fully fine.

1. In the org's Google account: create a Google Cloud project, enable the
   **YouTube Data API v3**, configure the OAuth consent screen.
2. Submit YouTube's **API compliance audit** (support.google.com →
   "YouTube API Services - Audit and Quota Extension Form"). Use case:
   publishing your own community meeting recordings to your own channel.
   Unaudited projects upload videos as PERMANENTLY LOCKED PRIVATE — do not
   enable before approval.
3. After approval: create an OAuth client (Desktop), run any standard OAuth
   flow for scope `https://www.googleapis.com/auth/youtube.upload` to obtain
   a refresh token, then:
   `modal secret create caic-youtube YT_CLIENT_ID=... YT_CLIENT_SECRET=...
   YT_REFRESH_TOKEN=... CAIC_YOUTUBE_UPLOAD=on`
4. Uncomment the `caic-youtube` secret line in `modal_app.py`, redeploy.
   Videos now upload as private with metadata pre-filled; the operator
   clicks Publish.

## Secrets recap

| Modal secret | Keys | Required |
|---|---|---|
| `caic-app` | `CAIC_PASSCODE` | yes |
| `caic-github` | `GITHUB_TOKEN`, `GITHUB_REPO` | yes |
| `caic-llm` | `CAIC_VLLM_BASE_URL`, `CAIC_VLLM_MODEL` | yes |
| `caic-youtube` | `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`, `CAIC_YOUTUBE_UPLOAD` | only for auto-upload |

Rotate the GitHub token yearly (it expires; calendar reminder recommended).
Nothing secret lives in the repo.
