# tests/unit/test_research_agent_types.py
"""Locks the dataclasses + defaults the rest of the package builds on, and the
standalone-purity rule (no madosho imports anywhere in the package)."""
from __future__ import annotations

import pathlib
import re

from research_agent import types as T


def test_budget_defaults():
    b = T.RunBudget()
    assert b.max_context_chars == 100_000
    assert b.max_rounds == 8
    assert T.DEFAULT_BUDGET_CHARS == 100_000
    assert T.DEFAULT_MAX_ROUNDS == 8


def test_dataclasses_construct():
    ep = T.LlmEndpoint(provider="openai", model="gpt-x")
    assert ep.api_key is None and ep.api_base is None
    spec = T.ToolSpec(name="search", description="d", parameters={"type": "object"})
    assert spec.name == "search"
    res = T.ToolResult(ok=True, data={"hits": []})
    assert res.ok and res.error is None
    call = T.ToolCall(id="c1", name="search", arguments={"corpus": "a", "query": "q"})
    turn = T.AssistantTurn(text=None, tool_calls=[call])
    assert turn.tool_calls[0].name == "search"
    cit = T.Citation(document_id=2, pipeline_id=3, pipeline="p", position=5,
                     citation="doc 2", source="f.pdf", score=0.9, quote="text")
    rep = T.Report(markdown="# Report", citations=[cit])
    assert rep.stop_reason == "final"
    assert rep.run_log == [] and rep.citations[0].document_id == 2


def test_no_madosho_imports():
    pkg = pathlib.Path("research_agent")
    offenders = []
    for f in pkg.rglob("*.py"):
        if re.search(r"^\s*(import|from)\s+madosho", f.read_text(encoding="utf-8"), re.M):
            offenders.append(str(f))
    assert offenders == [], f"research_agent must not import madosho: {offenders}"
