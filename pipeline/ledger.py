"""The concept ledger — CAIC's cross-meeting concept tracker.

Single source of truth: data/concepts.json in the GitHub repo. Every change
lands as part of the run's git commit, so history is the audit trail.

Ledger shape:
    {
      "schema_version": 1,
      "meetings": [{"date", "title", "slug", "summary_short"}, ...],
      "concepts": [{
          "name": str, "aliases": [str],
          "initiated": {"date", "meeting"},           # meeting = slug
          "mentions": [{"date", "meeting", "snippet", "depth"}],
          "status": "proposed|active|growing|dormant|completed",
          "last_updated": "YYYY-MM-DD"
      }, ...]
    }

STATUS RULES — simple, visible, deterministic (recomputed every run from the
mention history; no LLM involved). "completed" is set manually by a human
editing concepts.json and is never overridden:

  * proposed : mentioned in exactly 1 meeting so far
  * active   : mentioned in 2+ distinct meetings
  * growing  : mentioned in 3+ distinct meetings AND the latest mention was
               more than a passing reference (depth "discussed" or "deep-dive")
  * dormant  : not mentioned in any of the 3 most recent meetings on record
               (overrides the above once there are enough meetings to judge)

Uncertain LLM matches are NEVER silently merged — they are returned as review
items and surfaced in the run status for human confirmation.
"""

import re


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "item"


def _find_concept(ledger: dict, name: str):
    needle = name.strip().lower()
    for c in ledger["concepts"]:
        names = [c["name"]] + c.get("aliases", [])
        if needle in (n.strip().lower() for n in names):
            return c
    return None


def register_meeting(ledger: dict, meeting: dict) -> None:
    """Add/replace this meeting in the registry (re-runs overwrite cleanly)."""
    ledger.setdefault("meetings", [])
    ledger["meetings"] = [m for m in ledger["meetings"]
                          if m["slug"] != meeting["slug"]] + [meeting]
    ledger["meetings"].sort(key=lambda m: (m["date"], m["slug"]))


def apply_run(ledger: dict, meeting: dict, candidates: list, matches: list):
    """Apply one meeting's reconciled candidates to the ledger.

    Returns (review_items, change_log). Mutates `ledger` in place.
    """
    by_name = {c["name"]: c for c in candidates}
    review, changes = [], []

    for m in matches:
        cand = by_name.get(m["candidate"])
        if cand is None:
            continue  # model invented a candidate name; ignore
        mention = {"date": meeting["date"], "meeting": meeting["slug"],
                   "snippet": cand["snippet"], "depth": cand["depth"]}

        if m["verdict"] == "existing":
            concept = _find_concept(ledger, m.get("existing_name") or "")
            if concept is None:
                # Claimed match doesn't resolve — treat as uncertain, don't guess.
                review.append({"candidate": cand["name"],
                               "claimed_match": m.get("existing_name"),
                               "reason": "matched name not found in ledger"})
                continue
            if not any(x["meeting"] == meeting["slug"] and
                       x["snippet"] == mention["snippet"]
                       for x in concept["mentions"]):
                concept["mentions"].append(mention)
            concept["last_updated"] = meeting["date"]
            changes.append(f"mention: {concept['name']}")

        elif m["verdict"] == "new":
            if _find_concept(ledger, cand["name"]):
                changes.append(f"skip-duplicate: {cand['name']}")
                continue
            ledger["concepts"].append({
                "name": cand["name"], "aliases": [],
                "initiated": {"date": meeting["date"], "meeting": meeting["slug"]},
                "mentions": [mention],
                "status": "proposed",
                "last_updated": meeting["date"],
            })
            changes.append(f"new: {cand['name']}")

        else:  # "uncertain" — surface, never merge
            review.append({"candidate": cand["name"],
                           "claimed_match": m.get("existing_name"),
                           "reason": m.get("reason", "model was unsure")})

    update_statuses(ledger)
    return review, changes


def update_statuses(ledger: dict) -> None:
    """Recompute every concept's status from the rules in the module docstring."""
    meetings_order = [m["slug"] for m in ledger.get("meetings", [])]
    recent3 = set(meetings_order[-3:])

    for c in ledger["concepts"]:
        if c.get("status") == "completed":
            continue  # manual state — never overridden
        mentioned_in = {m["meeting"] for m in c["mentions"]}
        n = len(mentioned_in)
        last = max(c["mentions"], key=lambda m: m["date"], default=None)

        if len(meetings_order) >= 3 and not (mentioned_in & recent3):
            c["status"] = "dormant"
        elif n >= 3 and last and last["depth"] in ("discussed", "deep-dive"):
            c["status"] = "growing"
        elif n >= 2:
            c["status"] = "active"
        else:
            c["status"] = "proposed"
