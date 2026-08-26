# Operator Runbook — drop, RUN, collect

You do not need to be technical to run this. One page, three steps.

## Running a meeting through the pipeline

1. Open **https://hb-datag--caic-pipeline-web.modal.run** and enter the
   shared passcode.
2. Fill in the meeting **title** and **date**, then give it:
   * a **video** (it will be transcribed automatically), or
   * a **transcript** (file or pasted text), or
   * both (the transcript is trusted; transcription is skipped).
   Click **RUN**.
3. Watch the live feed. When it finishes you get links:
   * **Live summary page** — already public on the CAIC site
   * **Concept tracker** — updated automatically
   * **YouTube Kit** (video runs only) — see below

Typical duration: a pasted transcript finishes in ~2-4 minutes; a video adds
roughly 2-5 minutes per hour of recording.

You can close the page any time — the run continues. Come back later and
click the run under **Recent runs** to get your links.

## Publishing the video to YouTube (~2 minutes)

1. Download **final video (mp4)** and open **title, description, chapters**
   from the run's links.
2. Go to YouTube Studio → **Create → Upload videos** → pick the mp4.
3. Paste the title and the description (chapters included) from the text
   file. Publish.

## When something needs your attention

* **"NEEDS REVIEW" (yellow) in the feed** — the AI wasn't sure whether a
  concept matches an existing one. Nothing was merged. To resolve: open
  `data/concepts.json` in the GitHub repo (edit in the browser), and either
  add the candidate as a new concept or add its mention (and the new name as
  an alias) to the existing concept. Commit — the change is the audit trail.
* **"Please contact Haidar at 419-324-5282"** — the AI workstation is off
  or unreachable. Call Haidar; re-run the job after it's back.
* **A concept's status looks wrong** — statuses are recomputed automatically
  from simple rules (see README). Only `completed` is set by hand, by editing
  `status` in `data/concepts.json`.

## Occasional operator tasks

* **Change the passcode:** re-run
  `modal secret create caic-app CAIC_PASSCODE=newpass --force`
  then `modal deploy modal_app.py` from the repo folder.
* **Replace the intro clip:** put the real clip at `assets/caic_intro.mp4`
  in the repo folder (1080p/30fps H.264/AAC preferred) and redeploy.
* **The AI workstation rebooted:** nothing to do — Ollama, the whisper
  service, and the Tailscale funnel all auto-start.
