# tests/unit/test_research_agent_run.py
"""The public run() facade: default autonomous.md + default budget, override respected."""
from __future__ import annotations

import research_agent
from research_agent import load_default_autonomous_md, run
from research_agent.types import AssistantTurn, RunBudget, ToolSpec


class _NoTools:
    def manifest(self):
        return [ToolSpec(name="search", description="d", parameters={"type": "object"})]

    def invoke(self, name, args):
        raise AssertionError("should not be called in this test")


class _ImmediateLlm:
    """Captures the system message it receives, then returns a final report at once."""

    def __init__(self):
        self.system_seen = None

    def complete(self, messages, tools):
        self.system_seen = messages[0]["content"]
        return AssistantTurn(text="# Done", tool_calls=[])


def test_default_autonomous_md_is_nonempty_ascii():
    md = load_default_autonomous_md()
    assert md.strip()
    assert md.isascii(), "autonomous.md must be ASCII-only"
    assert "citation" in md.lower()


def test_run_uses_default_autonomous_md_and_budget():
    llm = _ImmediateLlm()
    report = run("What is X?", tools=_NoTools(), llm=llm)
    assert report.markdown == "# Done"
    # the default autonomous.md ended up in the system prompt
    assert "citation" in llm.system_seen.lower()


def test_run_respects_autonomous_md_override():
    llm = _ImmediateLlm()
    run("q", tools=_NoTools(), llm=llm, autonomous_md="CUSTOM-INSTRUCTIONS",
        budget=RunBudget(max_rounds=1))
    assert "CUSTOM-INSTRUCTIONS" in llm.system_seen


def test_public_surface_exports():
    for name in ["run", "Report", "Citation", "RunBudget", "LlmEndpoint",
                 "ToolProvider", "CliToolProvider", "LlmClient", "AnyLlmClient"]:
        assert hasattr(research_agent, name), f"missing export: {name}"
