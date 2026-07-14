"""Assemble per-section results into the report draft.

Purely mechanical (no LLM call): the orchestrator already holds every
section's content, so synthesis here would spend tokens to risk the model
rewriting evidence-grounded text. The template's structure IS the report's
structure. Unfilled sections state their shortfall inline so an exported
partial is honest on its face, not silently missing parts.

Duck-typed over SectionResult (title/key/content/filled/note) so it stays
import-light and trivially testable.
"""
from __future__ import annotations


def render_report(title: str, sections: list) -> str:
    parts = []
    if title:
        parts.append(f"# {title}")
    for s in sections:
        heading = s.title or s.key
        body = s.content if s.filled else f"_(not filled: {s.note or 'unknown'})_"
        parts.append(f"## {heading}\n\n{body}".rstrip())
    return "\n\n".join(parts) + "\n"
