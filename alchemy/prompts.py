"""User-prompt composition for a goal run.

The system prompt (behavior) stays research_agent's autonomous.md - the
research specialization. What alchemy varies is the USER prompt: the goal,
the corpus to scope tool calls to, and - on reruns - the prior draft plus
the user's guidance. WHY prior draft goes in the prompt rather than the
message history: the loop is stateless across runs by design (context dies
with the run); the draft is the only state worth carrying, and it is small.
"""
from __future__ import annotations

import pathlib

from .types import CompiledGoal, Section


def compose_prompt(compiled: CompiledGoal, *, corpus: str,
                   guidance: str | None = None,
                   prior_draft: str | None = None) -> str:
    parts = [
        f"Research goal: {compiled.goal}",
        f"Work ONLY within corpus {corpus!r}: pass it as the corpus argument "
        "to every search, and draw evidence only from documents in it.",
        "Write a report in markdown that fulfils the goal, grounded in what "
        "you retrieve.",
    ]
    if prior_draft:
        parts.append(
            "A prior draft of this report exists. Revise it - keep what is "
            "well-supported, improve what is not, and do not start over:\n"
            "--- Prior draft ---\n" + prior_draft + "\n--- End prior draft ---")
    if guidance:
        parts.append("The user reviewed the work so far and gave this "
                     "guidance; treat it as the top priority:\n" + guidance)
    return "\n\n".join(parts)


_REPORT_MD = pathlib.Path(__file__).parent / "report.md"


def load_report_md() -> str:
    """The report_agent prompt pack (behavior-as-data, like research_agent's
    autonomous.md). Passed to the loop as autonomous_md - the specialization
    seam the base agent already exposes, so research_agent stays frozen."""
    return _REPORT_MD.read_text(encoding="utf-8")


def compose_section_prompt(goal: str, section: Section, *, corpus: str,
                           guidance: str | None = None,
                           prior_content: str | None = None) -> str:
    """User prompt for one report work unit. Mirrors compose_prompt's rerun
    design: the prior SECTION content (not the whole report - the unit's
    context budget is per section) rides in the prompt, and user guidance is
    global - every unit sees it and applies what concerns its section."""
    parts = [
        f"Report goal: {goal}",
        f"Section to fill: {section.title or section.key}",
        f"Section instructions: {section.instruction}",
        f"Work ONLY within corpus {corpus!r}: pass it as the corpus argument "
        "to every search, and draw evidence only from documents in it.",
    ]
    if prior_content:
        parts.append(
            "A prior version of this section exists. Revise it - keep what "
            "is well-supported, improve what is not, and do not start over:\n"
            "--- Prior section ---\n" + prior_content + "\n--- End prior section ---")
    if guidance:
        parts.append("The user reviewed the report so far and gave this "
                     "guidance; where it concerns this section, treat it as "
                     "the top priority:\n" + guidance)
    return "\n\n".join(parts)


def compose_coverage_query(sections, goal: str) -> str:
    """The retrieval query for a forced pass: what the report still NEEDS,
    phrased from the weakest sections' headings and instructions. Capped at
    300 chars - retrieval queries degrade past that, and the sections' first
    words carry the topical signal. Falls back to the goal when nothing is
    weak (the pass then only proves consultation, it rarely changes text).

    Duck-typed over BOTH Section (has .instruction) and SectionResult (has
    only .title/.key) - the orchestrator hands weak SectionResults here, so
    .instruction is read defensively via getattr."""
    parts = []
    for s in sections:
        label = getattr(s, "title", "") or getattr(s, "key", "")
        instr = getattr(s, "instruction", "")
        parts.append(f"{label}: {instr}".rstrip(": ").rstrip())
    return ("; ".join(parts)[:300]) if parts else goal[:300]


def compose_forced_revision_prompt(goal: str, title: str, current: str,
                                   evidence: list[str]) -> str:
    """One-turn revision of a weak section with forced-coverage evidence in
    the prompt (the system already retrieved it - no tools needed, so the
    call count is deterministic: exactly one per revised section)."""
    ev = "\n".join(f"- {e}" for e in evidence)
    return (
        f"Report goal: {goal}\n\n"
        f"Section: {title}\n\n"
        "This section was written (or left unfilled) without consulting some "
        "corpus documents. The passages below were since retrieved from those "
        "documents. Revise the section to incorporate whatever is relevant; "
        "if nothing is, return the current text unchanged. Cite evidence you "
        "use with its citation string in square brackets.\n\n"
        f"--- Current section ---\n{current or '(empty)'}\n--- End current ---\n\n"
        f"--- New evidence ---\n{ev}\n--- End evidence ---\n\n"
        "Reply with ONLY the section body, then one final line exactly:\n"
        "CONFIDENCE: high|medium|low")
