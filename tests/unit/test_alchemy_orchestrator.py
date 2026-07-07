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
    # the ledger lists the corpus before any LLM call, so that call leads
    # tools.calls even on a plain living-research run (stage C)
    assert tools.calls == [("list-documents", {"corpus": "secdocs"}),
                           ("search", {"corpus": "secdocs", "query": "vulns"})]


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


# --- FIX A: carry prior sections forward when a rerun starves a section ------

def _prior(summary="prior summary text", june="prior june text"):
    return [{"key": "summary", "title": "Summary", "content": summary,
             "filled": True, "confidence": {"level": "high", "distinct_docs": 3,
                                            "citations": 5}},
            {"key": "june-incidents", "title": "June incidents",
             "content": june, "filled": True,
             "confidence": {"level": "medium", "distinct_docs": 2,
                            "citations": 2}}]


def test_rerun_carries_prior_into_capped_section():
    # cap=3, 2 sections: unit 1 runs within quota, unit 2 is starved (below the
    # 2-call floor). With priors, the starved section carries the prior text
    # instead of rendering a placeholder.
    class Searcher:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, tools):
            self.calls += 1
            if tools:
                return AssistantTurn(text=None, tool_calls=[
                    ToolCall(id=str(self.calls), name="search",
                             arguments={"corpus": "c", "query": "q"})])
            return AssistantTurn(text="fresh summary\n\nCONFIDENCE: low")

    result = alchemy.run_goal(
        "report", REPORT_SPEC, corpus="c", tools=FakeTools(),
        llm=Searcher(), budget=RunBudget(), max_llm_calls=3,
        prior_sections=_prior())
    assert result.stop_reason == "call_cap"
    june = result.sections[1]
    assert june.filled
    assert june.content == "prior june text"
    assert "carried from prior" in june.note and "call cap" in june.note
    # carried content shows in the assembled draft, no placeholder for it
    assert "prior june text" in result.markdown
    assert "_(not filled:" not in result.markdown
    # carried confidence rides from the prior, not a fresh blend
    assert june.confidence["level"] == "medium"


def test_rerun_carries_prior_after_cancel_before_unit_2():
    calls = {"n": 0}

    def should_cancel():
        calls["n"] += 1
        return calls["n"] > 2   # let unit 1 run, cancel before unit 2

    class OneShot:
        def complete(self, messages, tools):
            return AssistantTurn(text="fresh\n\nCONFIDENCE: high")

    result = alchemy.run_goal(
        "report", REPORT_SPEC, corpus="c", tools=FakeTools(),
        llm=OneShot(), should_cancel=should_cancel, prior_sections=_prior())
    assert result.stop_reason == "cancelled"
    assert result.sections[0].filled
    june = result.sections[1]
    assert june.filled and june.content == "prior june text"
    assert "carried from prior" in june.note and "cancelled" in june.note


def test_no_prior_still_renders_placeholder():
    # same starvation as above but WITHOUT priors: the section stays unfilled
    # and the draft carries the honest placeholder
    class Searcher:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, tools):
            self.calls += 1
            if tools:
                return AssistantTurn(text=None, tool_calls=[
                    ToolCall(id=str(self.calls), name="search",
                             arguments={"corpus": "c", "query": "q"})])
            return AssistantTurn(text="fresh\n\nCONFIDENCE: low")

    result = alchemy.run_goal(
        "report", REPORT_SPEC, corpus="c", tools=FakeTools(),
        llm=Searcher(), budget=RunBudget(), max_llm_calls=3)
    assert not result.sections[1].filled
    assert "_(not filled:" in result.markdown


# --- FIX B: a unit crash halts the run but keeps landed partials -------------

class _FillThenCrash:
    """Unit 1 answers on its first turn (fills section 1 in one call); the
    NEXT unit's first turn raises, so section 2's research loop crashes."""
    def __init__(self, boom="provider exploded"):
        self.calls = 0
        self.boom = boom

    def complete(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return AssistantTurn(text="filled\n\nCONFIDENCE: high")
        raise RuntimeError(self.boom)


def test_unit_crash_halts_run_keeps_partials():
    spec = {"template": ("## A\n\ndo a\n\n## B\n\ndo b\n\n## C\n\ndo c\n")}
    result = alchemy.run_goal(
        "report", spec, corpus="c", tools=FakeTools(), llm=_FillThenCrash(),
        budget=RunBudget())
    assert result.stop_reason == "failed"
    assert result.sections[0].filled            # section A survived
    assert not result.sections[1].filled
    assert result.sections[1].note.startswith("unit failed: RuntimeError")
    assert "provider exploded" in result.sections[1].note
    assert not result.sections[2].filled        # C skipped after the halt
    assert result.sections[2].note == "skipped: run failed"
    # the crash is swallowed by the engine, never escapes to the caller


def test_unit_crash_carries_prior_into_failed_section():
    result = alchemy.run_goal(
        "report", REPORT_SPEC, corpus="c", tools=FakeTools(),
        llm=_FillThenCrash(boom="boom"), budget=RunBudget(),
        prior_sections=_prior())
    assert result.stop_reason == "failed"
    june = result.sections[1]
    assert june.filled and june.content == "prior june text"
    assert june.note == "unit failed (carried prior, not revised): RuntimeError: boom"


# --- FIX G: run-level round_cap only from units that produced nothing --------

def test_round_cap_not_bubbled_when_every_section_filled():
    # each unit fills via a forced synthesis under its quota (unit stop_reason
    # round_cap) but the RUN cap is never tripped - a fully-filled run must
    # read "final", not the misleading "round_cap".
    class ForcedSynth:
        def complete(self, messages, tools):
            if tools:
                return AssistantTurn(text=None, tool_calls=[
                    ToolCall(id="x", name="search",
                             arguments={"corpus": "c", "query": "q"})])
            return AssistantTurn(text="filled\n\nCONFIDENCE: low")

    result = alchemy.run_goal(
        "report", REPORT_SPEC, corpus="c", tools=FakeTools(),
        llm=ForcedSynth(), budget=RunBudget(max_rounds=1))
    assert all(s.filled for s in result.sections)
    assert result.stop_reason == "final"


# --- Stage C task 3: every run carries an honest coverage ledger ------------

class LedgerFakeTools:
    """FakeTools plus a list-documents answer, so the ledger can size the
    corpus. Docs 1 and 2 exist; searches only ever hit doc 1."""
    def __init__(self, docs=None, listing_ok=True):
        self.docs = docs if docs is not None else [
            {"id": 1, "filename": "a.txt", "status": "indexed"},
            {"id": 2, "filename": "b.txt", "status": "indexed"}]
        self.listing_ok = listing_ok
        self.calls = []

    def manifest(self):
        return FakeTools().manifest()

    def invoke(self, name, args):
        self.calls.append((name, args))
        if name == "list-documents":
            if not self.listing_ok:
                return ToolResult(ok=False, error="listing down")
            return ToolResult(ok=True, data={"corpus": args.get("corpus"),
                                             "documents": list(self.docs)})
        return FakeTools().invoke(name, args)


def test_search_run_reports_honest_ledger():
    result = alchemy.run_goal(
        "living-research", {"goal": "map the vulns"}, corpus="secdocs",
        tools=LedgerFakeTools(), llm=_search_then_final())
    assert result.ledger is not None
    assert result.ledger["mode"] == "search"
    assert result.ledger["total_docs"] == 2
    assert result.ledger["consulted"] == {"1": "search"}
    assert result.ledger["complete"] is None
    assert result.ledger["summary"] == "consulted 1 of 2 docs (search-driven)"


def test_ledger_degrades_when_listing_fails():
    result = alchemy.run_goal(
        "living-research", {"goal": "map the vulns"}, corpus="secdocs",
        tools=LedgerFakeTools(listing_ok=False), llm=_search_then_final())
    assert result.ledger["total_docs"] is None
    assert "corpus size unknown" in result.ledger["summary"]


def test_report_run_builds_ledger_too():
    template = "# T\n\n## One\n\nfill\n\n## Two\n\nfill"
    llm = ScriptedLlm([
        AssistantTurn(text="one body\nCONFIDENCE: high", usage=None),
        AssistantTurn(text="two body\nCONFIDENCE: high", usage=None),
    ])
    result = alchemy.run_goal("report", {"template": template},
                              corpus="secdocs", tools=LedgerFakeTools(),
                              llm=llm)
    assert result.ledger["mode"] == "search"
    assert result.ledger["total_docs"] == 2


def test_prior_ledger_union_is_merged():
    result = alchemy.run_goal(
        "living-research", {"goal": "map the vulns"}, corpus="secdocs",
        tools=LedgerFakeTools(), llm=_search_then_final(),
        prior_ledger={"consulted": {"2": "search"}})
    assert result.ledger["consulted"] == {"1": "search", "2": "search"}
    assert result.ledger["from_prior"] == [2]


def test_unknown_coverage_mode_raises():
    import pytest
    with pytest.raises(ValueError):
        alchemy.run_goal("living-research", {"goal": "g"}, corpus="c",
                         tools=LedgerFakeTools(), llm=_search_then_final(),
                         coverage="vibes")


# --- Stage C task 5: full coverage - forced passes + weak-section revision ---

class FullCoverageTools(LedgerFakeTools):
    """search hits doc 1 only; search-doc serves the forced pass on doc 2."""
    def invoke(self, name, args):
        self.calls.append((name, args))
        if name == "list-documents":
            return ToolResult(ok=True, data={"corpus": args.get("corpus"),
                                             "documents": list(self.docs)})
        if name == "search-doc":
            return ToolResult(ok=True, data={"hits": [{
                "document_id": args["document_id"], "pipeline_id": 2,
                "pipeline": "p", "position": 1,
                "citation": f"doc {args['document_id']} @1",
                "source": "b.txt", "score": 0.8,
                "text": "forced evidence text"}]})
        return FakeTools().invoke(name, args)


def _one_section_template():
    return "# T\n\n## One\n\nfill it"


def test_full_coverage_forces_untouched_docs_and_revises():
    llm = ScriptedLlm([
        # unit for section One: searches (touches doc 1), then writes
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="1", name="search",
                     arguments={"corpus": "c", "query": "q"})], usage=None),
        AssistantTurn(text="body\nCONFIDENCE: high", usage=None),
        # forced revision of the weakest section with doc-2 evidence
        AssistantTurn(text="revised body\nCONFIDENCE: high", usage=None),
    ])
    tools = FullCoverageTools()
    result = alchemy.run_goal("report", {"template": _one_section_template()},
                              corpus="c", tools=tools, llm=llm,
                              coverage="full")
    assert result.ledger["consulted"] == {"1": "search", "2": "forced"}
    assert result.ledger["complete"] is True
    assert result.sections[0].content == "revised body"
    # forced retrieval was SYSTEM-side: a search-doc call for doc 2 happened
    assert ("search-doc", ) [0] in [c[0] for c in tools.calls]
    forced = [c for c in tools.calls if c[0] == "search-doc"]
    assert forced and forced[0][1]["document_id"] == 2
    # forced evidence is attributed like unit evidence
    assert any(c.document_id == 2 for c in result.citations)
    # complete coverage recorded in the blend
    assert result.sections[0].confidence["coverage_complete"] is True


def test_full_coverage_failure_reported_honestly():
    class FailingForce(FullCoverageTools):
        def invoke(self, name, args):
            if name == "search-doc":
                self.calls.append((name, args))
                return ToolResult(ok=False, error="pipeline missing")
            return super().invoke(name, args)

    llm = ScriptedLlm([
        # unit touches doc 1 via search, so only doc 2 is left unconsulted
        # for the forced pass to (fail to) reach
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="1", name="search",
                     arguments={"corpus": "c", "query": "q"})], usage=None),
        AssistantTurn(text="body\nCONFIDENCE: high", usage=None),
    ])
    result = alchemy.run_goal("report", {"template": _one_section_template()},
                              corpus="c", tools=FailingForce(), llm=llm,
                              coverage="full")
    assert result.ledger["complete"] is False
    assert result.ledger["failures"]["2"].startswith("pipeline missing")
    # incomplete coverage caps fresh sections at medium
    assert result.sections[0].confidence["level"] == "medium"
    assert result.sections[0].confidence["coverage_complete"] is False


class IncompleteCoverageHighFactsTools(LedgerFakeTools):
    """3 docs; search cites TWO of them (docs 1 and 3) so the unit's own
    facts earn the "high" ceiling (>=2 distinct docs) - unlike the other
    full-coverage tests above, where search only ever touches doc 1 and
    "medium" could just as easily be the 1-doc ceiling. The forced pass's
    search-doc on the untouched doc 2 FAILS, so coverage stays incomplete
    even though nothing about the section's own evidence was weak. This is
    what proves the confidence backfill (a real demotion), not the ceiling."""
    def __init__(self):
        super().__init__(docs=[
            {"id": 1, "filename": "a.txt", "status": "indexed"},
            {"id": 2, "filename": "b.txt", "status": "indexed"},
            {"id": 3, "filename": "c.txt", "status": "indexed"}])

    def invoke(self, name, args):
        self.calls.append((name, args))
        if name == "list-documents":
            return ToolResult(ok=True, data={"corpus": args.get("corpus"),
                                             "documents": list(self.docs)})
        if name == "search":
            return ToolResult(ok=True, data={"hits": [
                {"document_id": 1, "pipeline_id": 2, "pipeline": "p",
                 "position": 0, "citation": "doc 1 @0", "source": "a.txt",
                 "score": 0.9, "text": "evidence from doc one"},
                {"document_id": 3, "pipeline_id": 2, "pipeline": "p",
                 "position": 0, "citation": "doc 3 @0", "source": "c.txt",
                 "score": 0.85, "text": "evidence from doc three"}]})
        if name == "search-doc":
            return ToolResult(ok=False, error="pipeline missing")
        return ToolResult(ok=True, data={})


def test_full_coverage_demotes_genuine_high_not_just_low_doc_ceiling():
    # one search round citing 2 distinct docs, then a self-graded-high write -
    # on the facts alone this section clears the "high" ceiling outright
    llm = ScriptedLlm([
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="1", name="search",
                     arguments={"corpus": "c", "query": "q"})], usage=None),
        AssistantTurn(text="body\nCONFIDENCE: high", usage=None),
    ])
    result = alchemy.run_goal(
        "report", {"template": _one_section_template()}, corpus="c",
        tools=IncompleteCoverageHighFactsTools(), llm=llm, coverage="full")
    # run-level coverage never completed: doc 2's forced search-doc failed
    assert result.ledger["complete"] is False
    # the unit itself hit 2 distinct docs - the facts-ceiling here is "high",
    # so "medium" below can ONLY be the coverage backfill, not the 1-doc cap
    assert result.sections[0].confidence["distinct_docs"] == 2
    assert result.sections[0].confidence["coverage_complete"] is False
    assert result.sections[0].confidence["level"] == "medium"


def test_full_coverage_respects_call_cap():
    # cap = 2: the single section unit gets both calls (quota floor), leaving
    # nothing for the revision - forced RETRIEVAL still happens (free), the
    # revision is skipped, and the shortfall is stated.
    llm = ScriptedLlm([
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="1", name="search",
                     arguments={"corpus": "c", "query": "q"})], usage=None),
        AssistantTurn(text="body\nCONFIDENCE: high", usage=None),
    ])
    result = alchemy.run_goal("report", {"template": _one_section_template()},
                              corpus="c", tools=FullCoverageTools(), llm=llm,
                              coverage="full", max_llm_calls=2)
    assert result.usage.llm_calls == 2
    assert result.ledger["consulted"]["2"] == "forced"   # consultation is free
    assert result.sections[0].content == "body"          # no revision happened
    assert "llm call cap" in result.ledger["shortfall"]


def test_full_coverage_union_skips_docs_prior_run_covered():
    llm = ScriptedLlm([
        AssistantTurn(text="body\nCONFIDENCE: high", usage=None),
    ])
    tools = FullCoverageTools()
    result = alchemy.run_goal("report", {"template": _one_section_template()},
                              corpus="c", tools=tools, llm=llm,
                              coverage="full",
                              prior_ledger={"consulted": {"1": "search",
                                                          "2": "search"}})
    # nothing untouched -> no forced pass at all
    assert not [c for c in tools.calls if c[0] == "search-doc"]
    assert result.ledger["complete"] is True


def test_full_coverage_living_research_revises_draft():
    llm = ScriptedLlm([
        AssistantTurn(text="draft body", usage=None),           # the unit
        AssistantTurn(text="revised draft body", usage=None),   # revision
    ])
    tools = FullCoverageTools()
    result = alchemy.run_goal("living-research", {"goal": "g"}, corpus="c",
                              tools=tools, llm=llm, coverage="full")
    assert result.markdown == "revised draft body"
    assert result.ledger["consulted"]["2"] == "forced"
    assert result.ledger["complete"] is True


# --- Stage C task 6: exhaustive coverage - system-side reads + mining -------

class ExhaustiveTools(LedgerFakeTools):
    """get-doc serves whole-text reads for the mining phase."""
    def invoke(self, name, args):
        self.calls.append((name, args))
        if name == "list-documents":
            return ToolResult(ok=True, data={"corpus": args.get("corpus"),
                                             "documents": list(self.docs)})
        if name == "get-doc":
            return ToolResult(ok=True, data={
                "document_id": args["document_id"], "pipeline": "p",
                "pipeline_id": 2, "char_count": 9,
                "text": f"text of doc {args['document_id']}"})
        return FakeTools().invoke(name, args)


def test_exhaustive_mines_every_doc_then_writes():
    llm = ScriptedLlm([
        AssistantTurn(text="doc1 fact for One", usage=None),   # mine doc 1
        AssistantTurn(text="NOTHING RELEVANT", usage=None),    # mine doc 2
        AssistantTurn(text="body\nCONFIDENCE: high", usage=None),  # section
    ])
    tools = ExhaustiveTools()
    result = alchemy.run_goal("report", {"template": _one_section_template()},
                              corpus="c", tools=tools, llm=llm,
                              coverage="exhaustive")
    assert result.ledger["consulted"] == {"1": "read", "2": "read"}
    assert result.ledger["complete"] is True
    assert [c for c in tools.calls if c[0] == "get-doc"] == [
        ("get-doc", {"document_id": 1}), ("get-doc", {"document_id": 2})]
    # reads are attributed like the loop's get-doc citations
    assert any(c.document_id == 1 and "whole text" in c.citation
               for c in result.citations)
    assert result.sections[0].content == "body"


def test_exhaustive_digests_reach_the_section_prompt():
    seen = {}

    class SpyLlm:
        def __init__(self):
            self.n = 0

        def complete(self, messages, tools):
            self.n += 1
            if self.n <= 2:
                return AssistantTurn(text=f"fact {self.n}", usage=None)
            seen["user"] = [m for m in messages if m["role"] == "user"][0]["content"]
            return AssistantTurn(text="body\nCONFIDENCE: high", usage=None)

    alchemy.run_goal("report", {"template": _one_section_template()},
                     corpus="c", tools=ExhaustiveTools(), llm=SpyLlm(),
                     coverage="exhaustive")
    assert "fact 1" in seen["user"] and "fact 2" in seen["user"]


def test_exhaustive_reserves_write_budget():
    # cap = 3 with 1 section: reserve = 2, so mining may spend only 1 call.
    # Doc 1 gets mined; doc 2 must be left honestly unread, and the section
    # unit still runs inside its reserve.
    llm = ScriptedLlm([
        AssistantTurn(text="doc1 fact", usage=None),            # mine doc 1
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="1", name="search",
                     arguments={"corpus": "c", "query": "q"})], usage=None),
        AssistantTurn(text="body\nCONFIDENCE: high", usage=None),
    ])
    result = alchemy.run_goal("report", {"template": _one_section_template()},
                              corpus="c", tools=ExhaustiveTools(), llm=llm,
                              coverage="exhaustive", max_llm_calls=3)
    assert result.usage.llm_calls == 3
    assert result.ledger["consulted"]["1"] == "read"
    assert result.ledger["consulted"].get("2") != "read"
    assert result.ledger["complete"] is False
    assert "llm call cap" in result.ledger["shortfall"]
    assert result.sections[0].filled is True


def test_exhaustive_get_doc_failure_is_honest():
    class FailingRead(ExhaustiveTools):
        def invoke(self, name, args):
            if name == "get-doc" and args["document_id"] == 2:
                self.calls.append((name, args))
                return ToolResult(ok=False, error="no pipeline")
            return super().invoke(name, args)

    llm = ScriptedLlm([
        AssistantTurn(text="doc1 fact", usage=None),
        # section unit consults doc 1 itself via search, so its own
        # confidence blend has a citation to work with (not folded-in
        # corpus-wide mining credit)
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="1", name="search",
                     arguments={"corpus": "c", "query": "q"})], usage=None),
        AssistantTurn(text="body\nCONFIDENCE: high", usage=None),
    ])
    result = alchemy.run_goal("report", {"template": _one_section_template()},
                              corpus="c", tools=FailingRead(), llm=llm,
                              coverage="exhaustive")
    assert result.ledger["failures"]["2"].startswith("no pipeline")
    assert result.ledger["complete"] is False
    assert result.sections[0].confidence["level"] == "medium"
    assert result.sections[0].confidence["coverage_complete"] is False


def test_exhaustive_union_skips_docs_already_read():
    llm = ScriptedLlm([
        AssistantTurn(text="doc2 fact", usage=None),            # only doc 2
        AssistantTurn(text="body\nCONFIDENCE: high", usage=None),
    ])
    tools = ExhaustiveTools()
    result = alchemy.run_goal("report", {"template": _one_section_template()},
                              corpus="c", tools=tools, llm=llm,
                              coverage="exhaustive",
                              prior_ledger={"consulted": {"1": "read"}})
    reads = [c for c in tools.calls if c[0] == "get-doc"]
    assert reads == [("get-doc", {"document_id": 2})]
    assert result.ledger["complete"] is True


def test_exhaustive_living_research_mines_then_writes():
    seen = {}

    class SpyLlm:
        def __init__(self):
            self.n = 0

        def complete(self, messages, tools):
            self.n += 1
            if self.n <= 2:
                return AssistantTurn(text=f"fact {self.n}", usage=None)
            seen["user"] = [m for m in messages if m["role"] == "user"][0]["content"]
            return AssistantTurn(text="the answer", usage=None)

    result = alchemy.run_goal("living-research", {"goal": "g"}, corpus="c",
                              tools=ExhaustiveTools(), llm=SpyLlm(),
                              coverage="exhaustive")
    assert result.markdown == "the answer"
    assert "fact 1" in seen["user"]
    assert result.ledger["complete"] is True


def test_dedupe_matches_loop_semantics():
    from alchemy.orchestrator import _dedupe_citations
    from research_agent.types import Citation

    def cit(doc, pipe, pos, quote):
        return Citation(document_id=doc, pipeline_id=pipe, pipeline="p",
                        position=pos, citation="c", source=None, score=None,
                        quote=quote)

    # same passage via two tools (search hit, then whole-text get-doc):
    # different keys, identical (doc, quote) -> keep the first
    a = cit(1, 2, 0, "same text")
    b = cit(1, 9, None, "same text")
    assert _dedupe_citations([a, b]) == [a]
    # anonymous citations NEVER collapse, even with identical quotes
    x = cit(None, None, None, "anon")
    y = cit(None, None, None, "anon")
    assert _dedupe_citations([x, y]) == [x, y]
    # distinct positions on one doc both survive
    c = cit(1, 2, 0, "q0")
    d = cit(1, 2, 1, "q1")
    assert _dedupe_citations([c, d]) == [c, d]


def test_call_cap_backstop_mid_unit_keeps_landed_sections():
    """The CountingLlm BACKSTOP branch (except CallCapExceeded in the unit
    loop): reachable if the loop's call pattern ever changes, so it is pinned
    by raising the exception type from a scripted llm mid-unit."""
    from alchemy.llm import CallCapExceeded

    class BlowsOnSecondUnit:
        def __init__(self):
            self.n = 0

        def complete(self, messages, tools):
            self.n += 1
            if self.n == 1:
                return AssistantTurn(text="one body\nCONFIDENCE: high",
                                     usage=None)
            raise CallCapExceeded("llm call cap reached (backstop)")

    template = "# T\n\n## One\n\nfill\n\n## Two\n\nfill"
    result = alchemy.run_goal("report", {"template": template}, corpus="c",
                              tools=LedgerFakeTools(), llm=BlowsOnSecondUnit(),
                              max_llm_calls=50)
    assert result.stop_reason == "call_cap"
    assert result.sections[0].filled is True
    assert result.sections[0].content == "one body"
    assert result.sections[1].filled is False
    assert result.sections[1].note == "llm call cap"
