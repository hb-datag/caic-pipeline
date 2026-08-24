"""Job status store — a thin wrapper around a shared modal.Dict.

Every pipeline stage reports progress here; the web page polls it to show
the live status feed. One writer per job (the worker), so read-modify-write
is safe.

Job record shape:
    {
      "id": str, "title": str, "date": "YYYY-MM-DD",
      "inputs": {"video": path|None, "transcript": path|None},
      "state": "queued" | "running" | "done" | "error" | "needs-review",
      "stage": str,                      # current stage name
      "events": [{"t": epoch, "level": "info|warn|error", "msg": str}],
      "outputs": {name: url},            # links shown when done
      "review": [...],                   # uncertain concept matches (Phase 2)
      "created": epoch,
    }
"""

import time

import modal

JOBS_DICT = "caic-jobs"
RECENT_KEY = "_recent"  # rolling list of recent job ids
RECENT_MAX = 25

_handle = None


def _store():
    global _handle
    if _handle is None:
        _handle = modal.Dict.from_name(JOBS_DICT, create_if_missing=True)
    return _handle


def create_job(job_id: str, title: str, date: str, inputs: dict) -> dict:
    job = {
        "id": job_id,
        "title": title,
        "date": date,
        "inputs": inputs,
        "state": "queued",
        "stage": "queued",
        "events": [{"t": time.time(), "level": "info", "msg": "Job created"}],
        "outputs": {},
        "review": [],
        "created": time.time(),
    }
    s = _store()
    s[job_id] = job
    recent = s.get(RECENT_KEY, [])
    recent = [job_id] + [j for j in recent if j != job_id]
    s[RECENT_KEY] = recent[:RECENT_MAX]
    return job


def get(job_id: str):
    try:
        return _store()[job_id]
    except KeyError:
        return None


def recent() -> list:
    s = _store()
    out = []
    for jid in s.get(RECENT_KEY, []):
        job = get(jid)
        if job:
            out.append({k: job[k] for k in ("id", "title", "date", "state", "stage")})
    return out


def _update(job_id: str, mutate) -> None:
    s = _store()
    job = s[job_id]
    mutate(job)
    s[job_id] = job


def log(job_id: str, msg: str, level: str = "info") -> None:
    print(f"[{job_id}] {level}: {msg}")  # also lands in Modal logs
    _update(job_id, lambda j: j["events"].append(
        {"t": time.time(), "level": level, "msg": msg}))


def set_stage(job_id: str, stage: str) -> None:
    def mut(j):
        j["stage"] = stage
        j["state"] = "running"
        j["events"].append({"t": time.time(), "level": "info", "msg": f"— {stage} —"})
    _update(job_id, mut)


def add_review(job_id: str, item: dict) -> None:
    """Surface an uncertain concept match for human confirmation."""
    _update(job_id, lambda j: j.setdefault("review", []).append(item))


def add_output(job_id: str, name: str, url: str) -> None:
    _update(job_id, lambda j: j["outputs"].__setitem__(name, url))


def finish(job_id: str) -> None:
    def mut(j):
        j["state"] = "needs-review" if j.get("review") else "done"
        j["stage"] = "finished"
        j["events"].append({"t": time.time(), "level": "info", "msg": "Job finished"})
    _update(job_id, mut)


def fail(job_id: str, err: str) -> None:
    def mut(j):
        j["state"] = "error"
        j["events"].append({"t": time.time(), "level": "error", "msg": f"FAILED: {err}"})
    _update(job_id, mut)
