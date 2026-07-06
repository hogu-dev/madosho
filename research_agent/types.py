"""Core data types and Protocols for the research agent.

These are deliberately plain dataclasses + Protocols so the loop and its tests
stay free of any LLM-client or HTTP types. Every other module imports from here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_BUDGET_CHARS = 100_000   # ~25k tokens of source text; the read-whole-vs-search line
DEFAULT_MAX_ROUNDS = 8           # a couple of search rounds + synthesis; bounded so it cannot spin


@dataclass
class RunBudget:
    """Hard bounds on a run: total source chars fed to the model, and tool-call rounds."""
    max_context_chars: int = DEFAULT_BUDGET_CHARS
    max_rounds: int = DEFAULT_MAX_ROUNDS


@dataclass
class LlmEndpoint:
    """OpenAI-compatible endpoint config. Pluggable, no default - provider/model must be set.
    api_key/api_base arrive from env or flags and are never logged."""
    provider: str
    model: str
    api_key: str | None = None
    api_base: str | None = None


@dataclass
class ToolSpec:
    """One tool the model may call: name + description + JSON-Schema parameters.
    The invocation recipe (how to turn a call into argv) stays private to CliToolProvider."""
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolResult:
    """Outcome of invoking a tool. ok=False carries a structured error string the
    model can read and route around; the provider never raises into the loop."""
    ok: bool
    data: Any = None
    error: str | None = None


@dataclass
class ToolCall:
    """A normalized tool call from the model: id, tool name, parsed argument dict."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class AssistantTurn:
    """One model turn, normalized away from any LLM client's response object.
    text is the prose (final report when there are no tool_calls).
    usage is the provider's token accounting for THIS turn when the provider
    reports it (prompt/completion/total tokens) - optional and unread by the
    loop itself; consumers that meter spend (alchemy) sum it across turns."""
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict | None = None


@dataclass
class Citation:
    """A source the report draws on, gathered from a search hit or a whole-document read.
    Carries madosho's document/pipeline attribution so a claim links back to its chunk."""
    document_id: int | None
    pipeline_id: int | None
    pipeline: str | None
    position: int | None
    citation: str
    source: str | None
    score: float | None
    quote: str


@dataclass
class Report:
    """The deliverable: markdown body, the de-duplicated citations gathered during the run,
    a run log (every tool call + the stop reason), and why the loop ended."""
    markdown: str
    citations: list[Citation] = field(default_factory=list)
    run_log: list[dict] = field(default_factory=list)
    stop_reason: str = "final"   # one of: final | round_cap | no_tools_used | cancelled
