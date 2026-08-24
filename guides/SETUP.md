# First-time setup (you do these once — ~20 minutes)

Work through this top to bottom. Steps marked **(Phase 2)** or later can wait.

## 1. Modal account + CLI

1. Sign up at https://modal.com (free tier includes a monthly compute credit —
   this is the budget the whole pipeline runs on).
2. On your computer, in a terminal:

   ```
   pip install modal
   modal setup
   ```

   `modal setup` opens a browser window to authenticate. Done when the
   terminal says the token is stored.

## 2. Create the passcode secret

Pick a shared passcode for the upload page, then:

```
modal secret create caic-app CAIC_PASSCODE=your-passcode-here
```

(To change it later, re-run with the new value.)

## 3. First deploy

From this repo folder:

```
modal deploy modal_app.py
```

The output prints your app URL, something like
`https://<your-username>--caic-pipeline-web.modal.run`.
Open it, enter the passcode, and you should see the upload form.

Dev tip: `modal serve modal_app.py` runs a temporary live-reloading copy
while you edit.

## 4. GitHub repo

1. Create a **public** repo named `caic-pipeline` on your GitHub account
   (public is required for free GitHub Pages).
2. From this folder:

   ```
   git init
   git add .
   git commit -m "Phase 1: scaffold, Modal app, upload page + status feed"
   git branch -M main
   git remote add origin https://github.com/<your-username>/caic-pipeline.git
   git push -u origin main
   ```

## 5. Enable GitHub Pages

Repo → **Settings → Pages** → Source: **Deploy from a branch** →
Branch: **main**, folder: **/docs** → Save.

A minute later the placeholder site is live at
`https://<your-username>.github.io/caic-pipeline/`.

## 6. GitHub token secret (Phase 2)

The pipeline pushes generated summary pages by committing to this repo.

1. GitHub → Settings → Developer settings → **Fine-grained tokens** →
   Generate new token.
   * Repository access: **Only select repositories** → `caic-pipeline`
   * Permissions → Repository permissions → **Contents: Read and write**
   * Expiration: 1 year (put a calendar reminder to rotate it)
2. Add it to Modal:

   ```
   modal secret create caic-github GITHUB_TOKEN=github_pat_XXXX GITHUB_REPO=<your-username>/caic-pipeline
   ```

## 7. LLM server on the CAIC 5090 workstation (Phase 2)

The pipeline's intelligence runs on Haidar's always-on RTX 5090 machine via
Ollama, reached from Modal through a Tailscale Funnel URL. If this machine is
offline, runs fail with the operator contact message (configured in
`pipeline/config.py` → `OFFLINE_MESSAGE`).

### 7a. Ollama

1. Install from https://ollama.com/download (Windows). It runs in the tray
   and auto-starts on boot.
2. In a terminal: `ollama pull qwen3.6:27b`  (~17 GB download, one time)
3. Set these SYSTEM environment variables (Settings → System → About →
   Advanced system settings → Environment Variables), then quit and restart
   Ollama from the tray:
   * `OLLAMA_CONTEXT_LENGTH` = `40960`  (default is far too small for meetings)
   * `OLLAMA_FLASH_ATTENTION` = `1`
   * `OLLAMA_KV_CACHE_TYPE` = `q8_0`   (halves KV memory, negligible quality cost)
   * `OLLAMA_KEEP_ALIVE` = `30m`       (keeps the model warm between calls)
   * `OLLAMA_ORIGINS` = `*`            (accept requests arriving via the tunnel)
4. Sanity check: `curl http://localhost:11434/v1/models` should list the model.

### 7b. Tailscale Funnel (stable public URL)

1. Install Tailscale (https://tailscale.com/download), sign in (free plan).
2. In an **admin** terminal: `tailscale funnel --bg 11434`
   It prints your stable URL, like `https://<machine>.<tailnet>.ts.net`.
   `--bg` keeps it running across reboots.
3. Test from a phone (off wifi): open `https://<that-url>/v1/models`.

> Security note: that URL is publicly reachable and Ollama has no API auth —
> treat the URL itself as a secret (it lives only in the Modal secret below).

### 7c. Tell the pipeline about it

```
modal secret create caic-llm CAIC_VLLM_BASE_URL=https://<machine>.<tailnet>.ts.net CAIC_VLLM_MODEL=qwen3.6:27b
modal deploy modal_app.py
```

Backend swap for later (one setting, no code): set `CAIC_LLM_BACKEND=gemini`
(plus `GEMINI_API_KEY`) or `anthropic` (plus `ANTHROPIC_API_KEY`) in the
`caic-llm` secret, or point `CAIC_VLLM_BASE_URL` at any other
OpenAI-compatible server (e.g. the commented-out Modal vLLM function in
`modal_app.py`).

## 8. CAIC Google account (Phase 4)

Create a dedicated Google account for CAIC (Drive + YouTube channel).
Nothing to configure until Phase 4 — the YouTube Kit is uploaded manually
through YouTube Studio at first, so no API credentials are needed yet.

---

## Secrets recap

| Modal secret | Keys | Needed from |
|---|---|---|
| `caic-app` | `CAIC_PASSCODE` | Phase 1 (before first deploy) |
| `caic-github` | `GITHUB_TOKEN`, `GITHUB_REPO` | Phase 2 |
| `caic-llm` | `CAIC_VLLM_BASE_URL`, `CAIC_VLLM_MODEL` | Phase 2 |
| `caic-youtube` | (future) | after YouTube API audit |

Nothing secret ever goes in this repo.
