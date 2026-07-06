"""Spec compilation: every goal type collapses to the same CompiledGoal.

Stage A supports only living-research (spec = {"goal": "..."}), which
compiles to a single section keyed "body". The report type (stage B) will
add a markdown-template parser here WITHOUT touching the orchestrator -
that seam is the whole point of compiling.
"""
from __future__ import annotations

from .types import CompiledGoal, Section

GOAL_TYPES = ("living-research",)   # stage B adds "report"


def compile_spec(goal_type: str, spec: dict) -> CompiledGoal:
    if goal_type not in GOAL_TYPES:
        raise ValueError(f"unknown goal type: {goal_type!r} (stage A supports {GOAL_TYPES})")
    goal = (spec.get("goal") or "").strip()
    if not goal:
        raise ValueError("spec must carry a non-empty 'goal'")
    return CompiledGoal(goal=goal, sections=[Section(key="body", instruction=goal)])
