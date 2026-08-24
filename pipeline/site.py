"""Static site generator — Jinja2 templates -> plain HTML for GitHub Pages.

No JS frameworks; one shared stylesheet; CAIC blue palette. Returns a dict of
{repo_path: content} so the runner can commit everything atomically.

Pages built each run:
  docs/index.html                     meeting index (newest first)
  docs/meetings/<slug>/index.html     this run's summary page
  docs/concepts/index.html            sortable concept table
  docs/concepts/<slug>/index.html     one page per concept, with timeline
  docs/assets/style.css               shared stylesheet
"""

import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .ledger import slugify

TEMPLATE_DIRS = ["/root/site_templates", "site_templates"]


def _template_dir() -> str:
    for p in TEMPLATE_DIRS:
        if os.path.isdir(p):
            return p
    raise FileNotFoundError("site_templates directory not found")


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(_template_dir()),
                       autoescape=select_autoescape(["html"]))


def _concept_ctx(ledger: dict) -> list:
    """Enrich concepts with computed fields for templates (no ledger mutation)."""
    out = []
    for c in ledger["concepts"]:
        mentions = sorted(c["mentions"], key=lambda m: m["date"])
        out.append({
            **c,
            "slug": slugify(c["name"]),
            "n_meetings": len({m["meeting"] for m in mentions}),
            "first_date": c["initiated"]["date"],
            "last_date": mentions[-1]["date"] if mentions else c["initiated"]["date"],
        })
    return sorted(out, key=lambda c: c["name"].lower())


def build_run_pages(ledger: dict, meeting: dict, analysis: dict,
                    youtube_url: str | None = None) -> dict[str, str]:
    env = _env()
    files: dict[str, str] = {}

    files["docs/assets/style.css"] = (
        Path(_template_dir(), "style.css").read_text(encoding="utf-8"))

    files[f"docs/meetings/{meeting['slug']}/index.html"] = (
        env.get_template("meeting.html").render(
            root="../../", meeting=meeting, analysis=analysis,
            youtube_url=youtube_url))

    meetings = sorted(ledger.get("meetings", []),
                      key=lambda m: (m["date"], m["slug"]), reverse=True)
    files["docs/index.html"] = env.get_template("index.html").render(
        root="", meetings=meetings)

    concepts = _concept_ctx(ledger)
    files["docs/concepts/index.html"] = env.get_template(
        "concepts_index.html").render(root="../", concepts=concepts)

    meeting_order = sorted(ledger.get("meetings", []),
                           key=lambda m: (m["date"], m["slug"]))
    for c in concepts:
        cells = []
        for m in meeting_order:
            cells.append({
                "meeting": m,
                "mentions": [x for x in c["mentions"] if x["meeting"] == m["slug"]],
                "initiated": c["initiated"]["meeting"] == m["slug"],
            })
        files[f"docs/concepts/{c['slug']}/index.html"] = (
            env.get_template("concept.html").render(
                root="../../", concept=c, cells=cells))

    return files
