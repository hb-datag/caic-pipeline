"""Job orchestrator: decides which stages run based on what was uploaded.

INPUT LOGIC (from the project brief):
  * video only        -> extract audio -> whisper -> full pipeline
  * video + transcript-> skip whisper, trust the provided transcript
  * transcript only   -> analysis + site + concept ledger only (no video outputs)

Phase 2 is live: analyze -> concept-ledger -> publish-site work end-to-end.
Phases 3 (whisper) and 4 (video assembly / YouTube Kit) still log-and-skip.
"""

import json
from pathlib import Path

from . import status as st


def run_job(job_id: str) -> None:
    job = st.get(job_id)
    if job is None:
        raise RuntimeError(f"Unknown job {job_id}")

    try:
        inputs = job["inputs"]
        has_video = bool(inputs.get("video"))
        has_transcript = bool(inputs.get("transcript"))

        st.set_stage(job_id, "preflight")
        st.log(job_id, f"Inputs: video={'yes' if has_video else 'no'}, "
                       f"transcript={'yes' if has_transcript else 'no'}")

        if has_video and not has_transcript:
            st.set_stage(job_id, "transcribe")
            from .transcribe import transcribe_video
            txt_path = transcribe_video(
                inputs["video"], log=lambda m: st.log(job_id, m))
            job["inputs"]["transcript"] = str(txt_path)
            has_transcript = True

        if has_transcript:
            _run_transcript_pipeline(job_id, job)

        if has_video:
            st.set_stage(job_id, "video-assembly")
            # TODO(Phase 4): render branded slide, ffmpeg stitch
            # (intro -> slide -> recording), stream-copy fast path.
            st.log(job_id, "Video assembly not built yet (Phase 4) — skipping.", "warn")

            st.set_stage(job_id, "youtube-kit")
            # TODO(Phase 4): package final mp4 + title/description/chapters.
            # TODO(later): optional videos.insert upload-as-private step, once
            # the CAIC project passes YouTube's API audit.
            st.log(job_id, "YouTube Kit not built yet (Phase 4) — skipping.", "warn")

        st.finish(job_id)

    except Exception as exc:  # noqa: BLE001 — always record the failure
        from .llm import LLMError
        # LLMError messages are written for the operator (incl. the offline
        # contact message) — show them verbatim, not as a Python repr.
        st.fail(job_id, str(exc) if isinstance(exc, LLMError) else repr(exc))
        raise


# ---------------------------------------------------------------------------
# Phase 2: transcript -> analysis -> ledger -> public site
# ---------------------------------------------------------------------------

def _run_transcript_pipeline(job_id: str, job: dict) -> None:
    from . import analysis as an
    from . import ledger as lg
    from . import llm, site
    from .github_api import GitHubRepo

    title, date = job["title"], job["date"]

    # ---- analyze -------------------------------------------------------
    st.set_stage(job_id, "analyze")
    transcript = Path(job["inputs"]["transcript"]).read_text(
        encoding="utf-8", errors="replace")
    st.log(job_id, f"Transcript loaded: {len(transcript):,} characters")

    st.log(job_id, "Checking the model server…")
    llm.ensure_ready(log=lambda m: st.log(job_id, m, "warn"))
    st.log(job_id, "Model server ready.")

    result = an.run_analysis(transcript, title, date)
    st.log(job_id, f"Analysis done: {len(result['key_points'])} key points, "
                   f"{len(result['chapters'])} chapters, "
                   f"{len(result['decisions'])} decisions, "
                   f"{len(result['action_items'])} action items")

    candidates = an.extract_candidates(transcript, title, date)
    st.log(job_id, f"Concept candidates: {', '.join(c['name'] for c in candidates) or 'none'}")

    # ---- concept-ledger ------------------------------------------------
    st.set_stage(job_id, "concept-ledger")
    repo = GitHubRepo()
    raw = repo.get_file("data/concepts.json")
    ledger = json.loads(raw) if raw else {"schema_version": 1,
                                          "meetings": [], "concepts": []}
    ledger.setdefault("meetings", [])
    ledger.setdefault("concepts", [])

    meeting = {
        "date": date,
        "title": title,
        "slug": f"{date}-{lg.slugify(title)}",
        "summary_short": result["summary"].split("\n")[0][:220],
    }
    lg.register_meeting(ledger, meeting)

    if candidates and ledger["concepts"]:
        matches = an.reconcile(candidates, ledger)
    else:  # empty ledger: everything is trivially new — no LLM call needed
        matches = [{"candidate": c["name"], "verdict": "new"} for c in candidates]

    review, changes = lg.apply_run(ledger, meeting, candidates, matches)
    for ch in changes:
        st.log(job_id, f"ledger {ch}")
    for r in review:
        st.add_review(job_id, r)
        st.log(job_id, f"NEEDS REVIEW: '{r['candidate']}' — {r['reason']}"
                       + (f" (candidate match: {r['claimed_match']})"
                          if r.get("claimed_match") else ""), "warn")
    if review:
        st.log(job_id, "Uncertain matches were NOT merged. To resolve: edit "
                       "data/concepts.json in the repo (add as new concept, or "
                       "append the mention + alias to the existing one).", "warn")

    # ---- publish-site --------------------------------------------------
    st.set_stage(job_id, "publish-site")
    files = site.build_run_pages(ledger, meeting, result)
    files["data/concepts.json"] = json.dumps(ledger, indent=2) + "\n"
    files[f"docs/meetings/{meeting['slug']}/analysis.json"] = (
        json.dumps(result, indent=2) + "\n")  # raw output, kept for the audit trail

    sha = repo.commit_files(files, f"meeting: {title} ({date})")
    st.log(job_id, f"Committed {len(files)} files to {repo.repo} ({sha[:7]})")

    pages = repo.pages_base_url
    st.add_output(job_id, "Live summary page", f"{pages}/meetings/{meeting['slug']}/")
    st.add_output(job_id, "Concept tracker", f"{pages}/concepts/")
    st.log(job_id, "GitHub Pages usually refreshes within a minute of the commit.")
