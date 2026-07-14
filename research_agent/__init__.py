"""research_agent - a standalone, reusable research agent.

Given a prompt, an LLM, and a set of tools (discovered from a conforming CLI),
it runs a bounded retrieve-reason-retrieve loop and returns a cited report. It
imports nothing from madosho; madosho depends on it, never the reverse.
"""
from __future__ import annotations

from typing import Callable

from .agent_md import load_default_autonomous_md
from .llm import AnyLlmClient, LlmClient
from .loop import run_loop
from .tools import CliToolProvider, LlmkbToolProvider, MultiToolProvider, ToolProvider
from .types import (
    Citation,
    LlmEndpoint,
    Report,
    RunBudget,
    ToolResult,
    ToolSpec,
)

__all__ = [
    "run", "Report", "Citation", "RunBudget", "LlmEndpoint", "ToolSpec",
    "ToolResult", "ToolProvider", "CliToolProvider", "LlmkbToolProvider",
    "MultiToolProvider", "LlmClient", "AnyLlmClient",
    "load_default_autonomous_md",
]


def run(prompt: str, *, tools: ToolProvider, llm: LlmClient,
        autonomous_md: str | None = None, budget: RunBudget | None = None,
        should_cancel: Callable[[], bool] | None = None,
        on_event: Callable[[dict], None] | None = None) -> Report:
    """Run a research agent: gather evidence with the tools, write a cited report.

    autonomous_md defaults to the shipped instructions; budget defaults to RunBudget().
    should_cancel is an optional callback polled at the start of each round; when it
    returns True the loop exits immediately with stop_reason='cancelled'.
    on_event, when given, is called with each run_log entry as it is produced -
    the streaming seam for a live activity console (best-effort; see run_loop)."""
    md = autonomous_md if autonomous_md is not None else load_default_autonomous_md()
    b = budget if budget is not None else RunBudget()
    return run_loop(prompt, md, tools, llm, b, should_cancel=should_cancel,
                    on_event=on_event)
