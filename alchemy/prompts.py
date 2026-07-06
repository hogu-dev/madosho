"""User-prompt composition for a goal run.

The system prompt (behavior) stays research_agent's autonomous.md - the
research specialization. What alchemy varies is the USER prompt: the goal,
the corpus to scope tool calls to, and - on reruns - the prior draft plus
the user's guidance. WHY prior draft goes in the prompt rather than the
message history: the loop is stateless across runs by design (context dies
with the run); the draft is the only state worth carrying, and it is small.
"""
from __future__ import annotations

from .types import CompiledGoal


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
