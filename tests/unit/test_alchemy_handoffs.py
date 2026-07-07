"""Unit tests for the stage-D handoff helper in isolation.

These drive `_run_unit_with_handoffs` DIRECTLY, scripting research_agent.run
with a fake so the handoff control flow (round_cap -> continuation, the bounds,
the merge) is pinned without a full run_goal + real loop. End-to-end wiring is
covered in test_alchemy_orchestrator.py (Task 7)."""
from types import SimpleNamespace

import research_agent
from research_agent.types import Citation, Report, RunBudget

from alchemy.ledger import CoverageLedger
from alchemy.llm import CallCapExceeded
from alchemy.orchestrator import _run_unit_with_handoffs


def _cit(doc_id):
    return Citation(document_id=doc_id, pipeline_id=2, pipeline="p",
                    position=0, citation=f"doc {doc_id} @0", source=None,
                    score=0.9, quote="q")


class FakeRun:
    """Stands in for research_agent.run: returns scripted Reports in order,
    records each prompt it was handed (so a test can assert a continuation
    carried the partial), and bumps the passed llm's usage by `cost` calls so
    the helper's allowance math sees real spend. A scripted item that is an
    Exception is raised instead of returned (to model a backstop trip)."""
    def __init__(self, reports, cost=1):
        self.reports = list(reports)
        self.cost = cost
        self.prompts = []

    def __call__(self, prompt, *, tools, llm, budget=None, autonomous_md=None,
                 should_cancel=None):
        self.prompts.append(prompt)
        for _ in range(self.cost):
            llm.usage.llm_calls += 1
        item = self.reports.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _llm(max_calls=None):
    # the helper only reads .max_calls and .usage.llm_calls off the llm
    return SimpleNamespace(max_calls=max_calls,
                           usage=SimpleNamespace(llm_calls=0))


def _ledger(docs=(1, 2, 3)):
    return CoverageLedger(mode="search",
                          corpus_docs={d: f"doc{d}.txt" for d in docs})


def _echo_continuation(partial, docs_covered, remaining):
    return f"CONT[{remaining}]: {partial}"


def test_round_cap_then_final_merges_and_emits_one_handoff(monkeypatch):
    fake = FakeRun([
        Report(markdown="partial", citations=[_cit(1)],
               run_log=[{"round": 1}], stop_reason="round_cap"),
        Report(markdown="finished", citations=[_cit(2)],
               run_log=[{"round": 2}], stop_reason="final"),
    ])
    monkeypatch.setattr(research_agent, "run", fake)
    ledger = _ledger()
    merged, handoffs = _run_unit_with_handoffs(
        "P0", tools=object(), llm=_llm(), budget=None, autonomous_md=None,
        should_cancel=None, unit_key="body", ledger=ledger,
        max_handoffs=2, compose_continuation=_echo_continuation)
    # merge: last unit's markdown + stop, citations and run_log concatenated
    assert merged.markdown == "finished"
    assert merged.stop_reason == "final"
    assert [c.document_id for c in merged.citations] == [1, 2]
    assert merged.run_log == [{"round": 1}, {"round": 2}]
    # exactly one continuation spawned; it saw the partial draft
    assert fake.prompts[1].startswith("CONT[")
    assert "partial" in fake.prompts[1]
    # one handoff artifact with the frozen shape. docs_covered = the FIRST
    # unit's cited doc; remaining = the ledger's still-unconsulted docs at
    # handoff time (doc 1 was just marked, so 2 and 3 remain)
    assert len(handoffs) == 1
    h = handoffs[0]
    assert h["kind"] == "handoff" and h["key"] == "body-h1"
    assert h["payload"] == {"unit": "body", "attempt": 1,
                            "trigger": "round_cap", "docs_covered": [1],
                            "remaining": "documents not yet consulted: 2, 3",
                            "partial_chars": len("partial")}
    # each unit's citations were marked into the ledger by the helper
    assert ledger.consulted == {1: "search", 2: "search"}


def test_final_immediately_zero_handoffs(monkeypatch):
    fake = FakeRun([Report(markdown="done", citations=[], stop_reason="final")])
    monkeypatch.setattr(research_agent, "run", fake)
    merged, handoffs = _run_unit_with_handoffs(
        "P0", tools=object(), llm=_llm(), budget=None, autonomous_md=None,
        should_cancel=None, unit_key="body", ledger=_ledger(),
        max_handoffs=2, compose_continuation=_echo_continuation)
    assert merged.markdown == "done"
    assert handoffs == []
    assert len(fake.prompts) == 1        # no continuation was spawned


def test_max_handoffs_is_respected(monkeypatch):
    # every unit round-caps; with no call cap only max_handoffs bounds it
    fake = FakeRun([Report(markdown=f"p{i}", citations=[],
                           stop_reason="round_cap") for i in range(5)])
    monkeypatch.setattr(research_agent, "run", fake)
    merged, handoffs = _run_unit_with_handoffs(
        "P0", tools=object(), llm=_llm(), budget=None, autonomous_md=None,
        should_cancel=None, unit_key="body", ledger=_ledger(),
        max_handoffs=2, compose_continuation=_echo_continuation)
    # first unit + 2 continuations = 3 runs, then it stops
    assert len(fake.prompts) == 3
    assert [h["key"] for h in handoffs] == ["body-h1", "body-h2"]
    assert merged.stop_reason == "round_cap"   # still unfinished, honestly


def test_call_cap_floor_blocks_continuation(monkeypatch):
    # cap=3, first unit costs 2 -> only 1 call left, below the 2-call floor,
    # so NO continuation is spawned even though the unit round-capped
    fake = FakeRun([
        Report(markdown="partial", citations=[], stop_reason="round_cap"),
        Report(markdown="never", citations=[], stop_reason="final"),
    ], cost=2)
    monkeypatch.setattr(research_agent, "run", fake)
    merged, handoffs = _run_unit_with_handoffs(
        "P0", tools=object(), llm=_llm(max_calls=3), budget=RunBudget(),
        autonomous_md=None, should_cancel=None, unit_key="body",
        ledger=_ledger(), max_handoffs=2,
        compose_continuation=_echo_continuation)
    assert handoffs == []
    assert len(fake.prompts) == 1
    assert merged.markdown == "partial"        # honest partial survives


def test_should_cancel_mid_chain_stops_cleanly(monkeypatch):
    fake = FakeRun([Report(markdown=f"p{i}", citations=[],
                           stop_reason="round_cap") for i in range(5)])
    monkeypatch.setattr(research_agent, "run", fake)
    polls = {"n": 0}

    def should_cancel():
        polls["n"] += 1
        return polls["n"] > 1   # allow the first continuation, then cancel

    merged, handoffs = _run_unit_with_handoffs(
        "P0", tools=object(), llm=_llm(), budget=None, autonomous_md=None,
        should_cancel=should_cancel, unit_key="body", ledger=_ledger(),
        max_handoffs=5, compose_continuation=_echo_continuation)
    # one continuation spawned before the cancel poll tripped; stops cleanly
    assert len(handoffs) == 1
    assert len(fake.prompts) == 2


def test_continuation_backstop_preserves_partial(monkeypatch):
    # the continuation trips CountingLlm's backstop: the first unit's partial
    # + citations must survive rather than be lost to the cap trip
    fake = FakeRun([
        Report(markdown="partial", citations=[_cit(1)],
               stop_reason="round_cap"),
        CallCapExceeded("backstop"),
    ])
    monkeypatch.setattr(research_agent, "run", fake)
    merged, handoffs = _run_unit_with_handoffs(
        "P0", tools=object(), llm=_llm(max_calls=10), budget=RunBudget(),
        autonomous_md=None, should_cancel=None, unit_key="sec",
        ledger=_ledger(), max_handoffs=2,
        compose_continuation=_echo_continuation)
    assert merged.markdown == "partial"
    assert merged.stop_reason == "round_cap"
    assert [c.document_id for c in merged.citations] == [1]
    # the attempt genuinely happened and was metered, so its handoff dict stays
    assert len(handoffs) == 1 and handoffs[0]["key"] == "sec-h1"
