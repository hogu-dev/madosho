"""Core data types for the alchemy orchestration layer.

Plain dataclasses, mirroring research_agent/types.py in spirit: the
orchestrator and its tests stay free of HTTP and LLM-client types. Citations
are research_agent.Citation objects passed through untouched - alchemy adds
orchestration around the loop, it does not re-model the loop's outputs.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Section:
    """One thing to fill. Living-research has exactly one (key "body", no
    title); a report template compiles to many. key is a stable slug so
    confidence, citations, and rerun priors attribute per section; title is
    the human heading the renderer re-emits (empty for living-research)."""
    key: str
    instruction: str
    title: str = ""


@dataclass
class CompiledGoal:
    """The format-independent shape every spec compiles down to: a goal
    statement plus sections. The engine only ever sees this - it never knows
    whether the user authored freeform text, a markdown template, or a
    schema (that is the format layer's job, and WHY new formats cost no
    engine changes). title is the report's optional H1, used only by the
    renderer."""
    goal: str
    sections: list[Section] = field(default_factory=list)
    title: str = ""


@dataclass
class Usage:
    """Token/call accounting for one run, summed across every LLM turn.
    llm_calls counts turns (the honest self-cap number for rate-limited
    upstreams); token fields are 0 when a provider does not report usage,
    so totals are LOWER BOUNDS, never inventions."""
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class SectionResult:
    """One section's outcome from a report run. note says WHY when unfilled
    ("skipped: llm call cap", "cancelled", "no content produced",
    "unit failed: ...", "skipped: run failed") or, on a rerun that reused the
    prior run's text, why it was not revised ("carried from prior, not
    revised: ...") - the honest-shortfall principle applies per section, not
    just per run.
    confidence is blend_confidence's dict (level + the numbers behind it);
    llm_calls is this unit's share of the run's accounting."""
    key: str
    title: str = ""
    content: str = ""
    filled: bool = False
    note: str = ""
    confidence: dict = field(default_factory=dict)
    stop_reason: str = ""
    llm_calls: int = 0


@dataclass
class GoalRunResult:
    """What one goal run produces: the draft, the loop's mechanically
    gathered citations (research_agent.Citation objects), the run log, why
    it stopped, and what it spent."""
    markdown: str
    citations: list = field(default_factory=list)
    run_log: list[dict] = field(default_factory=list)
    stop_reason: str = "final"
    usage: Usage = field(default_factory=Usage)
    sections: list = field(default_factory=list)   # SectionResult per template
                                                   # section (report goals only)
    ledger: dict | None = None   # CoverageLedger.to_dict() - the honest
                                 # account of corpus consultation (stage C)
