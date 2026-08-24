# CAIC Video Pipeline

Automated meeting-video production for the **Cincinnati AI Catalyst (CAIC)**.

An operator uploads a meeting video and/or transcript on one web page, clicks
**RUN**, watches a live status feed, and gets back: a YouTube Kit (final video +
paste-ready title/description/chapters), a public summary page, and an updated
concept tracker.

**Hard constraint:** no paid LLM APIs. Everything runs on free tiers or
Modal's included monthly credit.

---

## How it works (plain language)

| Component | What it does |
|---|---|
| **Upload page** (`web/`) | A single passcode-protected page hosted on Modal. Operator drops in a video, a transcript, or both, plus title and date, and clicks RUN. |
| **RUN endpoint + status feed** (`modal_app.py`) | Receives the upload, stores it, kicks off a background job, and answers the page's polling requests so the operator sees live progress. |
| **Job runner** (`pipeline/runner.py`) | The conductor. Looks at what was uploaded and decides which stages run (see Input logic below). |
| **Transcription** *(Phase 3)* | If no transcript was provided, faster-whisper runs on a Modal GPU container (spun up per job, torn down after) with word-level timestamps. |
| **Intelligence** (`pipeline/llm.py`) | Key points, chapters, summaries, and concept extraction from Qwen3.6-27B (open weights) served by Ollama on CAIC's always-on RTX 5090 workstation, reached via a Tailscale Funnel URL. **Every** LLM call goes through one function, `generate(prompt, schema)`, so the backend can be swapped (any OpenAI-compatible server ↔ Gemini free tier ↔ Claude API) by changing one config value — a Modal-GPU vLLM variant sits commented-out in `modal_app.py` for successors without a GPU box. All outputs are schema-validated and retried once. If the workstation is offline, the run status shows a contact message instead of failing cryptically. |
| **Concept ledger** (`data/concepts.json`) | The novel piece: a single JSON file tracking every concept CAIC discusses across meetings — when it started, every mention, and a status (proposed → active → growing → dormant → completed). Every change is a git commit, so history is the audit trail. Uncertain matches are surfaced for human confirmation, never silently merged. |
| **Public site** (`docs/`) | Static HTML generated with Jinja2 (`site_templates/`) and pushed to this repo; GitHub Pages serves it from `/docs`. Index of meetings, per-meeting summary pages, and the concept tracker. Summary pages go live as soon as analysis finishes — before any video is public. |
| **Video assembly** *(Phase 4)* | FFmpeg stitches: CAIC intro → branded key-points slide (CAIC blue palette, rendered in Python) → meeting recording. Stream-copy fast path when the input is already 1080p/30fps/H.264/AAC. |
| **YouTube Kit** *(Phase 4)* | The final mp4 plus paste-ready title, description, and chapter list. The operator uploads via YouTube Studio (~2 min). Auto-upload is deliberately not built yet: unverified YouTube API projects lock uploads private. The code is structured so a `videos.insert` step can be slotted in after CAIC passes YouTube's API audit. |

## Input logic

| Uploaded | Pipeline |
|---|---|
| Video only | extract audio → whisper → analysis → site → video outputs |
| Video + transcript | skip whisper, trust the transcript |
| Transcript only | analysis → site → concept ledger only (no video outputs) |

## Repo layout

```
modal_app.py       Modal entrypoint: web app + job functions ("modal deploy modal_app.py")
pipeline/          All pipeline logic (config, LLM gateway, job runner, status store)
web/               The operator upload page (single HTML file)
site_templates/    Jinja2 templates for the public site (Phase 2)
docs/              GENERATED public site — served by GitHub Pages (don't hand-edit)
data/concepts.json The concept ledger (single source of truth)
assets/            caic_intro.mp4 lives here (placeholder title card until real intro exists)
guides/            Human documentation: setup, runbook, redeploy guide
```

## Build phases

| Phase | Scope | Status |
|---|---|---|
| 1 | Repo scaffold, Modal app skeleton, upload page + RUN + live status feed | **built — needs deploy test** |
| 2 | Transcript path end-to-end: LLM analysis → summary page → concept ledger → Pages push. Quality checkpoint on 2–3 real transcripts. | **built — needs deploy test + quality checkpoint** |
| 3 | faster-whisper transcription for video uploads | not started |
| 4 | Branded slide + FFmpeg stitch + YouTube Kit | not started |
| 5 | Operator runbook + successor redeploy guide | not started |

## Quickstart

See **`guides/SETUP.md`** for the full first-time walkthrough (Modal account,
secrets, GitHub, Pages). Once set up:

```
modal deploy modal_app.py      # deploy / update everything
modal serve modal_app.py       # dev mode with live reload
```

## Secrets (all live in Modal, never in this repo)

| Modal secret | Keys | Used from |
|---|---|---|
| `caic-app` | `CAIC_PASSCODE` | Phase 1 |
| `caic-github` | `GITHUB_TOKEN`, `GITHUB_REPO` | Phase 2 |
| `caic-llm` | `CAIC_VLLM_BASE_URL`, `CAIC_VLLM_MODEL` | Phase 2 |
| `caic-youtube` | (future) | Phase 4+ |
