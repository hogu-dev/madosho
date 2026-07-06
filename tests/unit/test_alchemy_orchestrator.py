import alchemy
from research_agent.types import (AssistantTurn, RunBudget, ToolCall,
                                  ToolResult, ToolSpec)


class FakeTools:
    def __init__(self):
        self.calls = []

    def manifest(self):
        return [ToolSpec(name="search", description="search corpus",
                         parameters={"type": "object", "properties": {
                             "corpus": {"type": "string"},
                             "query": {"type": "string"}},
                             "required": ["corpus", "query"]})]

    def invoke(self, name, args):
        self.calls.append((name, args))
        return ToolResult(ok=True, data={"hits": [{
            "document_id": 1, "pipeline_id": 2, "pipeline": "p",
            "position": 0, "citation": "doc 1 @0", "source": "d.txt",
            "score": 0.9, "text": "evidence text"}]})


class ScriptedLlm:
    def __init__(self, turns):
        self.turns = list(turns)

    def complete(self, messages, tools):
        return self.turns.pop(0)


def _search_then_final():
    return ScriptedLlm([
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="1", name="search",
                     arguments={"corpus": "secdocs", "query": "vulns"})],
            usage={"prompt_tokens": 10, "completion_tokens": 1,
                   "total_tokens": 11}),
        AssistantTurn(text="# Report\nfindings", usage={
            "prompt_tokens": 30, "completion_tokens": 20,
            "total_tokens": 50}),
    ])


def test_run_goal_end_to_end():
    tools = FakeTools()
    result = alchemy.run_goal(
        "living-research", {"goal": "map the vulns"}, corpus="secdocs",
        tools=tools, llm=_search_then_final(), budget=RunBudget())
    assert result.markdown == "# Report\nfindings"
    assert result.stop_reason == "final"
    assert len(result.citations) == 1
    assert result.citations[0].document_id == 1
    assert result.usage.llm_calls == 2
    assert result.usage.total_tokens == 61
    assert tools.calls == [("search", {"corpus": "secdocs", "query": "vulns"})]


def test_run_goal_revision_passes_draft_and_guidance():
    seen = {}

    class SpyLlm:
        def complete(self, messages, tools):
            seen.setdefault("first_user",
                            [m for m in messages if m["role"] == "user"][0])
            return AssistantTurn(text="revised", usage=None)

    result = alchemy.run_goal(
        "living-research", {"goal": "map the vulns"}, corpus="7",
        tools=FakeTools(), llm=SpyLlm(),
        guidance="dig into June", prior_draft="old body")
    assert result.markdown == "revised"
    content = seen["first_user"]["content"]
    assert "old body" in content and "dig into June" in content


def test_run_goal_bad_spec_raises():
    import pytest
    with pytest.raises(ValueError):
        alchemy.run_goal("living-research", {}, corpus="c",
                         tools=FakeTools(), llm=ScriptedLlm([]))


def test_run_goal_enforces_llm_call_cap():
    # an llm that would search forever; cap=1 leaves room for ONLY the
    # forced-synthesis turn (rounds clamp to 0), so the run still ends
    # with a draft instead of an error
    class EndlessSearcher:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, tools):
            self.calls += 1
            if tools:   # normal rounds keep searching
                return AssistantTurn(text=None, tool_calls=[
                    ToolCall(id=str(self.calls), name="search",
                             arguments={"corpus": "c", "query": "q"})])
            return AssistantTurn(text="# capped draft")   # synthesis turn

    llm = EndlessSearcher()
    result = alchemy.run_goal(
        "living-research", {"goal": "g"}, corpus="c", tools=FakeTools(),
        llm=llm, budget=RunBudget(), max_llm_calls=1)
    assert llm.calls == 1
    assert result.usage.llm_calls == 1
    assert result.markdown == "# capped draft"
    assert result.stop_reason == "round_cap"
