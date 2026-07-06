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


REPORT_SPEC = {"template": (
    "# Vuln report\n\nAssess the corpus.\n\n"
    "## Summary\n\nOne paragraph.\n\n"
    "## June incidents\n\nList each incident.\n")}


def _two_section_llm():
    """Each section unit: one search round, then a final with a self-grade."""
    return ScriptedLlm([
        # unit 1 (summary)
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="1", name="search",
                     arguments={"corpus": "secdocs", "query": "overview"})],
            usage={"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11}),
        AssistantTurn(text="All clear.\n\nCONFIDENCE: high",
                      usage={"prompt_tokens": 20, "completion_tokens": 5,
                             "total_tokens": 25}),
        # unit 2 (june incidents)
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="2", name="search",
                     arguments={"corpus": "secdocs", "query": "june"})],
            usage={"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11}),
        AssistantTurn(text="Two incidents found.\n\nCONFIDENCE: medium",
                      usage={"prompt_tokens": 20, "completion_tokens": 5,
                             "total_tokens": 25}),
    ])


def test_report_runs_one_unit_per_section():
    result = alchemy.run_goal(
        "report", REPORT_SPEC, corpus="secdocs", tools=FakeTools(),
        llm=_two_section_llm(), budget=RunBudget())
    assert result.stop_reason == "final"
    assert [s.key for s in result.sections] == ["summary", "june-incidents"]
    assert all(s.filled for s in result.sections)
    # marker stripped from content, kept as the self-grade
    assert result.sections[0].content == "All clear."
    assert result.sections[0].confidence["self_grade"] == "high"
    # FakeTools cites 1 distinct doc -> high self-grade capped at medium
    assert result.sections[0].confidence["level"] == "medium"
    assert result.sections[0].confidence["distinct_docs"] == 1
    # assembled draft carries title + headings + content
    assert result.markdown.startswith("# Vuln report\n")
    assert "## Summary\n\nAll clear." in result.markdown
    assert "## June incidents\n\nTwo incidents found." in result.markdown
    # accounting is run-total across units
    assert result.usage.llm_calls == 4
    assert result.usage.total_tokens == 72
    assert result.sections[0].llm_calls == 2
    # run log entries carry their section key
    assert all("section" in e for e in result.run_log)


def test_report_units_get_section_prompts_and_report_pack():
    seen = []

    class SpyLlm:
        def complete(self, messages, tools):
            seen.append((messages[0]["content"], messages[1]["content"]))
            return AssistantTurn(text="body\n\nCONFIDENCE: low", usage=None)

    alchemy.run_goal("report", REPORT_SPEC, corpus="secdocs",
                     tools=FakeTools(), llm=SpyLlm())
    assert len(seen) == 2
    system_1, user_1 = seen[0]
    assert "ONE section" in system_1          # report.md, not autonomous.md
    assert "Section to fill: Summary" in user_1
    assert "Section to fill: June incidents" in seen[1][1]


def test_report_call_cap_lands_partial_draft_not_error():
    # cap=3, 2 sections: unit 1 gets quota max(2, 3//2)=2 (one working
    # round + forced synthesis -> "partial" lands), leaving 1 remaining -
    # below the 2-call floor, so unit 2 is skipped honestly.
    class Searcher:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, tools):
            self.calls += 1
            if tools:
                return AssistantTurn(text=None, tool_calls=[
                    ToolCall(id=str(self.calls), name="search",
                             arguments={"corpus": "c", "query": "q"})])
            return AssistantTurn(text="partial\n\nCONFIDENCE: low")

    result = alchemy.run_goal(
        "report", REPORT_SPEC, corpus="c", tools=FakeTools(),
        llm=Searcher(), budget=RunBudget(), max_llm_calls=3)
    assert result.stop_reason == "call_cap"
    assert result.usage.llm_calls <= 3
    # both sections present; the first ran within its quota, the starved
    # second states its shortfall
    assert [s.key for s in result.sections] == ["summary", "june-incidents"]
    assert result.sections[0].filled
    assert result.sections[0].content == "partial"
    unfilled = [s for s in result.sections if not s.filled]
    assert unfilled == [result.sections[1]]
    assert all("call cap" in s.note for s in unfilled)
    assert "_(not filled:" in result.markdown
    # unfilled sections still carry explicit low confidence numbers
    assert all(s.confidence["level"] == "low" for s in unfilled)


def test_report_cancel_between_units():
    calls = {"n": 0}

    def should_cancel():
        calls["n"] += 1
        return calls["n"] > 2   # let unit 1 run, cancel before unit 2

    class OneShot:
        def complete(self, messages, tools):
            return AssistantTurn(text="done\n\nCONFIDENCE: high")

    result = alchemy.run_goal(
        "report", REPORT_SPEC, corpus="c", tools=FakeTools(),
        llm=OneShot(), should_cancel=should_cancel)
    assert result.stop_reason == "cancelled"
    assert result.sections[0].filled
    assert not result.sections[1].filled


def test_report_rerun_threads_prior_sections_by_key():
    seen = []

    class SpyLlm:
        def complete(self, messages, tools):
            seen.append(messages[1]["content"])
            return AssistantTurn(text="revised\n\nCONFIDENCE: low", usage=None)

    prior = [{"key": "summary", "title": "Summary", "content": "old summary",
              "filled": True},
             {"key": "june-incidents", "title": "June incidents",
              "content": "old june", "filled": True}]
    alchemy.run_goal("report", REPORT_SPEC, corpus="c", tools=FakeTools(),
                     llm=SpyLlm(), prior_sections=prior,
                     guidance="expand June")
    assert "old summary" in seen[0]
    assert "old june" in seen[1]
    assert all("expand June" in p for p in seen)


def test_report_on_progress_reports_sections():
    events = []
    result = alchemy.run_goal(
        "report", REPORT_SPEC, corpus="secdocs", tools=FakeTools(),
        llm=_two_section_llm(), on_progress=events.append)
    assert result.stop_reason == "final"
    assert events[0] == {"phase": "running", "section": "summary",
                         "sections_done": 0, "sections_total": 2}
    assert events[1]["section"] == "june-incidents"


def test_living_research_unchanged_no_sections():
    result = alchemy.run_goal(
        "living-research", {"goal": "map the vulns"}, corpus="secdocs",
        tools=FakeTools(), llm=_search_then_final(), budget=RunBudget())
    assert result.sections == []
    assert result.markdown == "# Report\nfindings"
