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
                   prior_draft: str | None = None,
                   digests_text: str | None = None) -> str:
    parts = [
        f"Research goal: {compiled.goal}",
        f"Work ONLY within corpus {corpus!r}: pass it as the corpus argument "
        "to every search, and draw evidence only from documents in it.",
        "Write a report in markdown that fulfils the goal, grounded in what "
        "you retrieve.",
    ]
    if digests_text:
        parts.append(
            "Evidence digests from an exhaustive read of the corpus (mined "
            "mechanically, doc by doc). Use them to know WHERE evidence "
            "lives, and verify with search/search-doc before relying on "
            "details:\n" + digests_text)
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


MINING_MD = """You are mining one document for a report. You will receive a
part of the document's extracted text and the report's section list. Reply
with compact findings: concrete facts from THIS text that serve any listed
section, each on its own line, tagged with the section it serves and quoting
the key phrase. Do not summarize the document; extract only what the sections
need. If nothing in this text is relevant to any section, reply with exactly:
NOTHING RELEVANT"""


def compose_mining_prompt(goal: str, sections, doc_id: int, filename: str,
                          part_text: str, part_no: int, parts_total: int) -> str:
    """User prompt for one mining call: one slice of one document, plus the
    report's section list so the model knows what to extract for. Paired
    with MINING_MD as the system prompt (a plain complete() call, no tools -
    mining reads text it was already handed, it does not retrieve)."""
    sec_lines = "\n".join(f"- {s.title or s.key}: {s.instruction}"
                          for s in sections)
    return (
        f"Report goal: {goal}\n\n"
        f"Sections to serve:\n{sec_lines}\n\n"
        f"Document to mine: document {doc_id} ({filename}), "
        f"part {part_no} of {parts_total}.\n\n"
        f"--- Document text ---\n{part_text}\n--- End document text ---")


def compose_section_prompt(goal: str, section: Section, *, corpus: str,
                           guidance: str | None = None,
                           prior_content: str | None = None,
                           digests_text: str | None = None) -> str:
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
    if digests_text:
        parts.append(
            "Evidence digests from an exhaustive read of the corpus (mined "
            "mechanically, doc by doc). Use them to know WHERE evidence "
            "lives, and verify with search/search-doc before relying on "
            "details:\n" + digests_text)
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
    weak, or when the weak sections carry no topical signal (e.g. living-
    research's untitled "body" section) - the pass then only proves
    consultation, it rarely changes text.

    Duck-typed over BOTH Section (has .instruction) and SectionResult (has
    only .title/.key) - the orchestrator hands weak SectionResults here, so
    .instruction is read defensively via getattr."""
    parts = []
    for s in sections:
        # Topical signal only: a section's heading and instruction. The bare
        # structural key ("body" for living-research) is NOT topical - a
        # section with neither a title nor an instruction contributes nothing,
        # so the query falls back to the goal. Without this a living-research
        # `full` pass searched every doc for the literal word "body", making
        # the forced sweep topically random.
        title = getattr(s, "title", "") or ""
        instr = getattr(s, "instruction", "") or ""
        piece = f"{title}: {instr}".strip().strip(":").strip()
        if piece:
            parts.append(piece)
    return ("; ".join(parts)[:300]) if parts else goal[:300]


def compose_continuation_prompt(goal: str, *, corpus: str, partial: str,
                                docs_covered: list, remaining: str,
                                section: Section | None = None,
                                guidance: str | None = None) -> str:
    """The prompt for a HANDOFF continuation unit. A prior unit ran out of its
    round budget (loop stop_reason 'round_cap') with the draft below still
    unfinished; this fresh unit resumes from that partial instead of starting
    over. WHY the partial rides in the prompt (not message history): the loop
    is stateless across runs by design - the draft is the only state worth
    carrying, exactly as compose_prompt does for a rerun's prior_draft. The
    unit is also told which documents were already consulted (so it spends its
    fresh budget on NEW ground, not re-reading) and what work still remains.

    Shared by BOTH goal paths: living-research passes section=None (continue
    the whole body); a report passes the Section being filled (continue only
    it, keeping the per-section context budget)."""
    target = (f"section {section.title or section.key!r}"
              if section is not None else "report")
    parts = [
        f"Research goal: {goal}",
        f"You are CONTINUING an unfinished {target}. A prior work unit ran out "
        "of its research-round budget before finishing. Resume its work - do "
        "NOT start over.",
        f"Work ONLY within corpus {corpus!r}: pass it as the corpus argument "
        "to every search, and draw evidence only from documents in it.",
    ]
    if section is not None:
        parts.append(f"Section instructions: {section.instruction}")
    if docs_covered:
        parts.append(
            "Documents the prior unit already consulted (do not re-read these "
            "unless a detail needs verifying; find NEW evidence): "
            + ", ".join(str(d) for d in docs_covered))
    parts.append("Work still outstanding: " + remaining)
    parts.append(
        "--- Draft so far (keep what is well-supported, then extend and finish "
        "it) ---\n"
        + (partial or "(the prior unit produced no draft text)")
        + "\n--- End draft so far ---")
    if guidance:
        parts.append("The user reviewed the work so far and gave this "
                     "guidance; treat it as the top priority:\n" + guidance)
    return "\n\n".join(parts)


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
