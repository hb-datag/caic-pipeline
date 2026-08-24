"""Meeting intelligence — every prompt in the pipeline lives here.

Three LLM calls per run, all through pipeline.llm.generate() (schema-validated,
one retry):
  1. run_analysis()       summary, key points, chapters, decisions, actions
  2. extract_candidates() concept candidates from this transcript
  3. reconcile()          match candidates against the existing ledger

Transcripts may or may not contain timestamps (pasted text often doesn't);
prompts and schemas tolerate both.
"""

from . import llm, schemas

# ~120k chars ≈ 30k tokens — fits the 40k context window configured on the
# Ollama server (OLLAMA_CONTEXT_LENGTH in SETUP.md §7) with room for output.
MAX_TRANSCRIPT_CHARS = 120_000


def _clip(transcript: str) -> str:
    if len(transcript) <= MAX_TRANSCRIPT_CHARS:
        return transcript
    half = MAX_TRANSCRIPT_CHARS // 2
    return (transcript[:half] + "\n\n[... middle of transcript omitted "
            "for length ...]\n\n" + transcript[-half:])


def run_analysis(transcript: str, title: str, date: str) -> dict:
    prompt = f"""Analyze this meeting transcript for the Cincinnati AI Catalyst (CAIC).

Meeting: {title}
Date: {date}

Produce a JSON object with exactly these keys:
- "summary": 2-3 paragraph plain-language recap of what happened
- "key_points": 4-7 of the most important points, each {{"text", "timestamp"}}.
  Use "HH:MM:SS" timestamps ONLY if the transcript contains them, else null.
- "chapters": chapter list for YouTube, each {{"title", "start"}} with "HH:MM:SS"
  start times. If the transcript has no timestamps, return [].
- "decisions": list of decisions actually made (strings). [] if none.
- "action_items": each {{"text", "owner"}}; "owner" is a name if stated, else null.

Be faithful to the transcript — do not invent facts, names, or timestamps.

TRANSCRIPT:
{_clip(transcript)}"""
    return llm.generate(prompt, schemas.ANALYSIS_SCHEMA)


def extract_candidates(transcript: str, title: str, date: str) -> list:
    prompt = f"""You are building CAIC's concept tracker. From this meeting transcript
({title}, {date}), extract the distinct CONCEPTS discussed: ideas, initiatives,
projects, proposals, or recurring themes the group is developing.

NOT concepts: generic terms ("AI", "the meeting"), logistics (scheduling,
attendance), or one-off small talk.

Return JSON: {{"candidates": [{{"name", "snippet", "depth"}}]}}
- "name": short canonical name (2-5 words)
- "snippet": a short quote (max 25 words) from the transcript showing the mention
- "depth": "passing" (mentioned briefly), "discussed" (real conversation),
  or "deep-dive" (a main focus of the meeting)

Typically 3-8 candidates. Fewer is fine.

TRANSCRIPT:
{_clip(transcript)}"""
    return llm.generate(prompt, schemas.CONCEPT_CANDIDATES_SCHEMA)["candidates"]


def reconcile(candidates: list, ledger: dict) -> list:
    existing = [{"name": c["name"], "aliases": c.get("aliases", [])}
                for c in ledger["concepts"]]
    cand_list = [{"name": c["name"], "snippet": c["snippet"]} for c in candidates]

    prompt = f"""CAIC keeps a ledger of concepts tracked across meetings. Decide whether each
new candidate concept IS one of the existing ledger concepts (same idea under
the same or a different name), is genuinely NEW, or is UNCERTAIN.

EXISTING LEDGER CONCEPTS:
{existing}

NEW CANDIDATES FROM THIS MEETING:
{cand_list}

Return JSON: {{"matches": [{{"candidate", "verdict", "existing_name", "reason"}}]}}
- "candidate": the candidate's name, exactly as given above
- "verdict": "existing" | "new" | "uncertain"
- "existing_name": the matched ledger concept's exact name if verdict is
  "existing" (or your best guess if "uncertain"), else null
- "reason": one short sentence

CRITICAL RULE: only answer "existing" when you are CONFIDENT it is the same
concept. If in doubt, answer "uncertain" — a wrong merge corrupts the ledger,
while "uncertain" just asks a human. Include every candidate exactly once."""
    return llm.generate(prompt, schemas.RECONCILE_SCHEMA)["matches"]
