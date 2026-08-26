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

        analysis_result = meeting = None
        if has_transcript:
            analysis_result, meeting = _run_transcript_pipeline(job_id, job)

        if has_video and analysis_result:
            from . import video as vid

            st.set_stage(job_id, "video-assembly")
            workdir = str(Path(inputs["video"]).parent / "assembly")
            final, offset, fast = vid.assemble(
                inputs["video"], job["title"], job["date"],
                analysis_result["key_points"], workdir,
                log=lambda m: st.log(job_id, m))

            st.set_stage(job_id, "youtube-kit")
            from .github_api import GitHubRepo
            pages_url = (f"{GitHubRepo().pages_base_url}"
                         f"/meetings/{meeting['slug']}/")
            text = vid.build_youtube_text(job["title"], job["date"],
                                          analysis_result, offset, pages_url)
            jobdir = Path(inputs["video"]).parent
            (jobdir / "youtube.txt").write_text(text, encoding="utf-8")
            # final.mp4 lives in assembly/; expose both via the download API
            base = f"/api/download/{job_id}"
            st.add_output(job_id, "YouTube Kit — final video (mp4)",
                          f"{base}/final.mp4")
            st.add_output(job_id, "YouTube Kit — title, description, chapters",
                          f"{base}/youtube.txt")
            from . import youtube_upload as yt
            if yt.enabled():
                try:
                    url = yt.upload_private(
                        final, f"{job['title']} | Cincinnati AI Catalyst — "
                               f"{job['date']}", text,
                        log=lambda m: st.log(job_id, m))
                    st.add_output(job_id, "YouTube (uploaded private — "
                                          "click Publish in Studio)", url)
                except Exception as exc:  # noqa: BLE001 — kit still works
                    st.log(job_id, f"YouTube auto-upload failed ({exc}); "
                                   "use the kit manually.", "warn")
            else:
                st.log(job_id, "YouTube Kit ready — download, then upload via "
                               "YouTube Studio (~2 min). Auto-upload activates "
                               "after the YouTube API audit (see REDEPLOY.md).")

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

def _run_transcript_pipeline(job_id: str, job: dict):
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
    return result, meeting
