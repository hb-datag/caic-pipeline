"""JSON schemas for every LLM output (used by pipeline.llm.generate).

Drafts for Phase 2 — refined at the quality checkpoint. Keeping them here,
next to the LLM gateway, makes the contract between prompts and code visible.
"""

# One call: full meeting analysis
ANALYSIS_SCHEMA = {
    "type": "object",
    "required": ["summary", "key_points", "chapters", "decisions", "action_items"],
    "properties": {
        "summary": {"type": "string"},
        "key_points": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["text"],
                "properties": {
                    "text": {"type": "string"},
                    "timestamp": {"type": ["string", "null"]},  # "HH:MM:SS" if known
                },
            },
        },
        "chapters": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "start"],
                "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string"},  # "HH:MM:SS"
                },
            },
        },
        "decisions": {"type": "array", "items": {"type": "string"}},
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["text"],
                "properties": {
                    "text": {"type": "string"},
                    "owner": {"type": ["string", "null"]},
                },
            },
        },
    },
}

# Call 1 of the concept ledger: extract candidates from this transcript
CONCEPT_CANDIDATES_SCHEMA = {
    "type": "object",
    "required": ["candidates"],
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "snippet", "depth"],
                "properties": {
                    "name": {"type": "string"},
                    "snippet": {"type": "string"},   # short quote showing the mention
                    "depth": {"enum": ["passing", "discussed", "deep-dive"]},
                },
            },
        }
    },
}

# Call 2: reconcile candidates against the existing ledger.
# Bias hard toward "uncertain" — a false merge is worse than an extra
# human confirmation.
RECONCILE_SCHEMA = {
    "type": "object",
    "required": ["matches"],
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["candidate", "verdict"],
                "properties": {
                    "candidate": {"type": "string"},
                    "verdict": {"enum": ["existing", "new", "uncertain"]},
                    "existing_name": {"type": ["string", "null"]},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}
