"""Alchemy: the orchestration layer over corpus-grounded autonomous goals.

Public API: run_goal (the engine) plus the result types. Depends on
research_agent as a library (one-way); imports nothing from madosho_server.
"""
from .orchestrator import run_goal
from .types import (CompiledGoal, GoalRunResult, Section, SectionResult,
                    Usage)

__all__ = ["run_goal", "GoalRunResult", "Usage", "CompiledGoal", "Section",
           "SectionResult"]
