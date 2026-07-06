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
    """One thing to fill. Stage A (living-research) has exactly one; the
    report goal type (stage B) will compile a template into many. key is a
    stable identifier so later stages can attribute confidence and citations
    per section."""
    key: str
    instruction: str


@dataclass
class CompiledGoal:
    """The format-independent shape every spec compiles down to: a goal
    statement plus sections. The engine only ever sees this - it never knows
    whether the user authored freeform text, a markdown template, or a
    schema (that is the format layer's job, and WHY new formats cost no
    engine changes)."""
    goal: str
    sections: list[Section] = field(default_factory=list)


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
class GoalRunResult:
    """What one goal run produces: the draft, the loop's mechanically
    gathered citations (research_agent.Citation objects), the run log, why
    it stopped, and what it spent."""
    markdown: str
    citations: list = field(default_factory=list)
    run_log: list[dict] = field(default_factory=list)
    stop_reason: str = "final"
    usage: Usage = field(default_factory=Usage)
