"""Per-section confidence: self-grade blended with citation facts.

WHY blend instead of trusting the model: a self-grade alone is vibes - the
spec requires that "a section the model calls high-confidence citing 1 of 14
docs gets marked down". The mechanical facts available in stage B are the
unit's citations (gathered from tool traffic, never model claims): distinct
contributing documents cap the level. min(self_grade, fact_ceiling) means the
model can only LOWER what the facts would allow, never raise it. Coverage
facts join the blend in stage C.

The self-grade travels as a final "CONFIDENCE: high|medium|low" line in the
unit's reply (the report prompt pack mandates it). Parsing a trailing marker
line costs zero extra LLM calls; a missing/mangled marker degrades to a
neutral "medium" rather than failing the section.
"""
from __future__ import annotations

import re

LEVELS = ("low", "medium", "high")   # ascending

_MARKER = re.compile(r"^\s*confidence\s*:\s*(high|medium|low)\s*$", re.IGNORECASE)


def split_grade_marker(text: str) -> tuple[str, str | None]:
    """Strip a trailing self-grade marker line; return (content, grade|None).
    Only the LAST line counts - a marker mid-text is report content."""
    lines = text.rstrip().splitlines()
    if lines:
        m = _MARKER.match(lines[-1])
        if m:
            return "\n".join(lines[:-1]).rstrip(), m.group(1).lower()
    return text, None


def blend_confidence(self_grade: str | None, citations: list) -> dict:
    """Blend the model's self-grade with citation facts. Returns the level
    PLUS the numbers behind it - never a bare adjective."""
    distinct_docs = len({getattr(c, "document_id", None) for c in citations
                         if getattr(c, "document_id", None) is not None})
    ceiling = "low" if distinct_docs == 0 else (
        "medium" if distinct_docs == 1 else "high")
    base = self_grade if self_grade in LEVELS else "medium"
    level = min(base, ceiling, key=LEVELS.index)
    return {"level": level, "self_grade": self_grade,
            "distinct_docs": distinct_docs, "citations": len(citations)}
