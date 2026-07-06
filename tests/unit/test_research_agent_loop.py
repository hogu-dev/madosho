# tests/unit/test_research_agent_loop.py
"""Drives run_loop with a fake ToolProvider + a scripted LlmClient: no network, no
real model. Asserts the loop calls tools, assembles citations, enforces the round
cap and the budget, and records a run log."""
from __future__ import annotations

from research_agent.loop import run_loop
from research_agent.types import AssistantTurn, RunBudget, ToolCall, ToolResult, ToolSpec


class FakeTools:
    """In-test ToolProvider: a fixed manifest + canned results keyed by tool name."""

    def __init__(self, results):
        self.results = results            # name -> ToolResult
        self.calls = []                   # list[(name, args)]

    def manifest(self):
        return [
            ToolSpec(name="search", description="RAG retrieval.",
                     parameters={"type": "object",
                                 "properties": {"corpus": {"type": "string"},
                                                "query": {"type": "string"}},
                                 "required": ["corpus", "query"]}),
        ]

    def invoke(self, name, args):
        self.calls.append((name, args))
        return self.results[name]


class ScriptedLlm:
    """Returns queued AssistantTurns in order; records the tool schemas it was given."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.tool_args_seen = []

    def complete(self, messages, tools):
        self.tool_args_seen.append(tools)
        return self.turns.pop(0)


SEARCH_HIT = ToolResult(ok=True, data={"hits": [
    {"text": "AFTI uses triple-redundant sensors.", "score": 0.9, "page": 12,
     "citation": "AFTI manual p12", "source": "afti.pdf",
     "document_id": 2, "position": 5, "pipeline_id": 3, "pipeline": "aero_docling"}]})


def test_loop_calls_tool_then_writes_report():
    tools = FakeTools({"search": SEARCH_HIT})
    llm = ScriptedLlm([
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="c1", name="search",
                     arguments={"corpus": "aerospace", "query": "sensor failure"})]),
        AssistantTurn(text="# Report\nAFTI uses redundant sensors [AFTI manual p12].",
                      tool_calls=[]),
    ])
    report = run_loop("How does AFTI handle sensor failures?", "You are a researcher.",
                      tools, llm, RunBudget())
    assert tools.calls == [("search", {"corpus": "aerospace", "query": "sensor failure"})]
    assert report.markdown.startswith("# Report")
    assert report.stop_reason == "final"
    # citation gathered from the search hit, with attribution
    assert len(report.citations) == 1
    c = report.citations[0]
    assert c.document_id == 2 and c.pipeline == "aero_docling" and c.position == 5
    # run log has the two llm turns + one tool call
    kinds = [e["kind"] for e in report.run_log]
    assert kinds.count("llm") == 2 and kinds.count("tool_call") == 1
    # first turn was offered the search tool schema
    assert llm.tool_args_seen[0][0]["function"]["name"] == "search"


def test_round_cap_forces_synthesis():
    tools = FakeTools({"search": SEARCH_HIT})
    # every turn keeps calling the tool; never emits a final on its own
    # NOTE: range(2) matches max_rounds=2 so the queue is [L0, L1, synthesis];
    # the loop consumes L0+L1, then the forced-synthesis call pops synthesis.
    # (Controller-directed fix: brief had range(5) which leaves looping[2] as
    # the synthesis pop target, causing markdown="" and the assertion to fail.)
    looping = [AssistantTurn(text=None, tool_calls=[
        ToolCall(id=f"c{i}", name="search", arguments={"corpus": "a", "query": "q"})])
        for i in range(2)]
    synthesis = AssistantTurn(text="# Forced report", tool_calls=[])
    llm = ScriptedLlm(looping + [synthesis])
    report = run_loop("q", "agent", tools, llm, RunBudget(max_rounds=2))
    assert report.stop_reason == "round_cap"
    assert report.markdown == "# Forced report"
    # 2 rounds of tool calls, then a tool-less synthesis call (empty tools list)
    assert llm.tool_args_seen[-1] == []


def test_budget_truncates_oversized_tool_result():
    big = ToolResult(ok=True, data={"hits": [{"text": "x" * 1000, "citation": "c",
                                              "document_id": 1, "pipeline_id": 1,
                                              "position": 0, "pipeline": "p"}]})
    tools = FakeTools({"search": big})
    llm = ScriptedLlm([
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="c1", name="search", arguments={"corpus": "a", "query": "q"})]),
        AssistantTurn(text="done", tool_calls=[]),
    ])
    report = run_loop("q", "agent", tools, llm, RunBudget(max_context_chars=200))
    tool_entry = [e for e in report.run_log if e["kind"] == "tool_call"][0]
    assert tool_entry["chars"] <= 200
    assert tool_entry["note"] == "truncated to fit context budget"


def test_failed_tool_is_reported_not_raised():
    tools = FakeTools({"search": ToolResult(ok=False, error="corpus not found")})
    llm = ScriptedLlm([
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="c1", name="search", arguments={"corpus": "nope", "query": "q"})]),
        AssistantTurn(text="# Report despite error", tool_calls=[]),
    ])
    report = run_loop("q", "agent", tools, llm, RunBudget())
    tool_entry = [e for e in report.run_log if e["kind"] == "tool_call"][0]
    assert tool_entry["ok"] is False and "corpus not found" in tool_entry["error"]
    assert report.citations == []           # no citations from a failed call
    assert report.markdown == "# Report despite error"


def test_first_turn_empty_is_no_tools_used():
    """A model that produces nothing on the first turn -> no_tools_used, empty report."""
    tools = FakeTools({"search": SEARCH_HIT})
    llm = ScriptedLlm([
        AssistantTurn(text=None, tool_calls=[]),
    ])
    report = run_loop("q", "agent", tools, llm, RunBudget())
    assert report.stop_reason == "no_tools_used"
    assert report.markdown == ""
    assert report.citations == []


def test_empty_turn_after_tools_falls_through_to_synthesis():
    """Regression for FIX 1: a degenerate empty turn on round 2+ must NOT discard
    gathered citations. The forced-synthesis block must run and salvage the report."""
    tools = FakeTools({"search": SEARCH_HIT})
    llm = ScriptedLlm([
        # round 1: a real search
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="c1", name="search",
                     arguments={"corpus": "aerospace", "query": "sensor failure"})]),
        # round 2: degenerate empty turn (text=None, no tool calls)
        AssistantTurn(text=None, tool_calls=[]),
        # forced synthesis call (called by the if-not-got_final block)
        AssistantTurn(text="# Salvaged report", tool_calls=[]),
    ])
    report = run_loop("q", "agent", tools, llm, RunBudget())
    assert report.markdown == "# Salvaged report"
    assert report.stop_reason == "round_cap"
    assert len(report.citations) == 1   # citation from round 1 preserved, NOT discarded


def test_cancel_stops_at_next_round():
    """should_cancel returning True at start of round 2 exits early with stop_reason=='cancelled'."""
    tools = FakeTools({"search": SEARCH_HIT})
    # counter: False on round 1, True on round 2 onwards
    call_count = {"n": 0}

    def should_cancel():
        call_count["n"] += 1
        return call_count["n"] >= 2

    # round 1 makes a tool call; round 2 would too, but the cancel fires before llm.complete
    llm = ScriptedLlm([
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="c1", name="search",
                     arguments={"corpus": "aerospace", "query": "sensor failure"})]),
        # this turn must not be reached
        AssistantTurn(text="# Full report", tool_calls=[]),
    ])
    report = run_loop("q", "agent", tools, llm, RunBudget(max_rounds=5),
                      should_cancel=should_cancel)
    assert report.stop_reason == "cancelled"
    # only round 1 completed: one llm entry in the log, fewer than a full run
    llm_entries = [e for e in report.run_log if e["kind"] == "llm"]
    assert len(llm_entries) == 1
    # run_log from the completed round is preserved (not discarded)
    assert len(report.run_log) > 0


def test_dedupe_collapses_same_document_same_quote_across_tools():
    """A `search` hit and a whole-text `get-doc` of the SAME passage arrive with
    different (doc, pipeline, position) keys but identical text. Keep the first,
    better-attributed one - not a second copy with null source/score."""
    from research_agent.loop import _dedupe
    from research_agent.types import Citation

    QUOTE = "This agreement runs for two years."
    search_cit = Citation(document_id=1, pipeline_id=10, pipeline="docling", position=0,
                          citation="contract.pdf p.1", source="contract.pdf", score=0.79,
                          quote=QUOTE)
    gettext_cit = Citation(document_id=1, pipeline_id=None, pipeline=None, position=None,
                           citation="document 1 (whole text)", source=None, score=None,
                           quote=QUOTE)
    out = _dedupe([search_cit, gettext_cit])
    assert len(out) == 1
    assert out[0] is search_cit            # the attributed one survives

    # distinct quotes from the same document are NOT collapsed
    other = Citation(document_id=1, pipeline_id=10, pipeline="docling", position=1,
                     citation="contract.pdf p.1", source="contract.pdf", score=0.5,
                     quote="Invoices are payable within thirty days.")
    assert len(_dedupe([search_cit, other])) == 2

    # anonymous citations (no document_id) are never collapsed, even on equal text
    anon = Citation(document_id=None, pipeline_id=None, pipeline=None, position=None,
                    citation="", source=None, score=None, quote=QUOTE)
    assert len(_dedupe([anon, anon])) == 2
