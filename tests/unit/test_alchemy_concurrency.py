"""Stage E: concurrency safety for the alchemy engine.

The fakes here are deliberately NOT order-keyed (no pop(0)): once two units
run at the same time, call order is meaningless, so scripted replies key off
prompt CONTENT and synchronization primitives (Barrier/Event) pin the
interleavings the tests need to prove.
"""
import threading
import time

import pytest

import alchemy
from alchemy.llm import CallCapExceeded, CountingLlm
from research_agent.types import AssistantTurn, RunBudget, ToolCall, ToolResult, ToolSpec


class SlowInner:
    """Inner client that dwells inside the call, so an unguarded
    check-then-increment has a wide-open TOCTOU window to fall into."""
    def __init__(self, delay=0.05):
        self.delay = delay
        self.calls = 0
        self._lock = threading.Lock()

    def complete(self, messages, tools):
        with self._lock:
            self.calls += 1
        time.sleep(self.delay)
        return AssistantTurn(text="ok", usage={"prompt_tokens": 1,
                                               "completion_tokens": 1,
                                               "total_tokens": 2})


def test_cap_never_oversubscribed_under_threads():
    # 8 threads released together against a cap of 3: the upstream provider
    # must NEVER see more than 3 calls, and exactly 5 threads must be refused
    # with CallCapExceeded. The old check-then-increment let all 8 pass the
    # check before any increment landed.
    inner = SlowInner()
    llm = CountingLlm(inner, max_calls=3)
    n = 8
    start = threading.Barrier(n)
    outcomes = []
    out_lock = threading.Lock()

    def worker():
        start.wait()
        try:
            llm.complete([], [])
            with out_lock:
                outcomes.append("ok")
        except CallCapExceeded:
            with out_lock:
                outcomes.append("capped")

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert inner.calls == 3
    assert outcomes.count("ok") == 3
    assert outcomes.count("capped") == 5
    assert llm.usage.llm_calls == 3
    assert llm.usage.prompt_tokens == 3   # token sums not lost to torn +=


def test_failed_provider_call_releases_its_slot():
    # only calls actually made are counted - a provider crash must not burn
    # a cap slot (same observable rule as the pre-lock implementation)
    class Boom:
        def complete(self, messages, tools):
            raise RuntimeError("provider down")

    class Ok:
        def complete(self, messages, tools):
            return AssistantTurn(text="ok", usage=None)

    llm = CountingLlm(Boom(), max_calls=2)
    try:
        llm.complete([], [])
    except RuntimeError:
        pass
    assert llm.usage.llm_calls == 0
    llm.inner = Ok()
    llm.complete([], [])
    llm.complete([], [])   # both slots still available after the failure
    assert llm.usage.llm_calls == 2


def test_snapshot_is_a_consistent_copy():
    class OneShotInner:
        def complete(self, messages, tools):
            return AssistantTurn(text="ok", usage={"prompt_tokens": 5,
                                                   "completion_tokens": 1,
                                                   "total_tokens": 6})

    llm = CountingLlm(OneShotInner())
    llm.complete([], [])
    snap = llm.snapshot()
    assert snap == llm.usage
    assert snap is not llm.usage
    llm.complete([], [])
    assert snap.llm_calls == 1       # the copy did not move with the live counter
    assert llm.usage.llm_calls == 2


# --- C2: CoverageLedger is threadsafe -----------------------------------

from alchemy.ledger import CoverageLedger


def test_ledger_to_dict_never_tears_under_concurrent_marks():
    # to_dict() sorts consulted.items() - an insert landing mid-sort raises
    # "RuntimeError: dictionary changed size during iteration". Hammer it:
    # one thread marks 30k docs while another snapshots continuously.
    ledger = CoverageLedger(mode="search",
                            corpus_docs={i: f"d{i}" for i in range(50)})
    done = threading.Event()
    errors = []

    def writer():
        for i in range(30_000):
            ledger.mark(i, "search")
        done.set()

    def reader():
        while not done.is_set():
            try:
                ledger.to_dict()
            except RuntimeError as e:   # pragma: no cover - the bug branch
                errors.append(e)
                done.set()
                return

    r = threading.Thread(target=reader)
    w = threading.Thread(target=writer)
    r.start()
    w.start()
    w.join()
    r.join()
    assert errors == []
    assert len(ledger.consulted) == 30_000


def test_concurrent_marks_keep_strongest_and_lose_none():
    ledger = CoverageLedger(mode="full",
                            corpus_docs={i: f"d{i}" for i in range(100)})

    def mark_all(how):
        for i in range(100):
            ledger.mark(i, how)

    threads = [threading.Thread(target=mark_all, args=(how,))
               for how in ("search", "forced", "read", "search")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # strongest evidence wins per doc; no mark is lost
    assert all(ledger.consulted[i] == "read" for i in range(100))
    assert ledger.unconsulted() == []
    assert ledger.complete() is True


# --- C3: run_goal concurrency param + parallel report path ----------------

REPORT_SPEC = {"template": (
    "# Vuln report\n\nAssess the corpus.\n\n"
    "## Summary\n\nOne paragraph.\n\n"
    "## June incidents\n\nList each incident.\n")}


class ConcurrencyTools:
    """Threadsafe fake tools: a 2-doc corpus listing (the ledger needs its
    denominator) and a search that always hits doc 1."""
    def __init__(self):
        self._lock = threading.Lock()
        self.calls = []

    def manifest(self):
        return [ToolSpec(name="search", description="search corpus",
                         parameters={"type": "object", "properties": {
                             "corpus": {"type": "string"},
                             "query": {"type": "string"}},
                             "required": ["corpus", "query"]})]

    def invoke(self, name, args):
        with self._lock:
            self.calls.append((name, args))
        if name == "list-documents":
            return ToolResult(ok=True, data={
                "corpus": args.get("corpus"), "documents": [
                    {"id": 1, "filename": "a.txt", "status": "indexed"},
                    {"id": 2, "filename": "b.txt", "status": "indexed"}]})
        return ToolResult(ok=True, data={"hits": [{
            "document_id": 1, "pipeline_id": 2, "pipeline": "p",
            "position": 0, "citation": "doc 1 @0", "source": "d.txt",
            "score": 0.9, "text": "evidence text"}]})


class SectionKeyedLlm:
    """Concurrency-safe scripted llm: the reply keys off the section named in
    the user prompt ('Section to fill: <title>'), never off call order -
    order-keyed pop(0) fakes are meaningless once two units interleave."""
    def __init__(self, replies: dict[str, str]):
        self.replies = dict(replies)

    def complete(self, messages, tools):
        user = [m for m in messages if m["role"] == "user"][0]["content"]
        for title, reply in self.replies.items():
            if f"Section to fill: {title}" in user:
                return AssistantTurn(text=reply, usage=None)
        raise AssertionError("no scripted reply matches prompt: " + user[:120])


def test_concurrency_must_be_positive():
    with pytest.raises(ValueError):
        alchemy.run_goal("report", REPORT_SPEC, corpus="c",
                         tools=ConcurrencyTools(), llm=SectionKeyedLlm({}),
                         concurrency=0)


def test_parallel_report_fills_all_sections_in_template_order():
    events = []
    result = alchemy.run_goal(
        "report", REPORT_SPEC, corpus="c", tools=ConcurrencyTools(),
        llm=SectionKeyedLlm({
            "Summary": "sum body\n\nCONFIDENCE: high",
            "June incidents": "june body\n\nCONFIDENCE: medium"}),
        budget=RunBudget(), concurrency=2, on_progress=events.append)
    assert result.stop_reason == "final"
    assert [s.key for s in result.sections] == ["summary", "june-incidents"]
    assert all(s.filled for s in result.sections)
    assert result.sections[0].content == "sum body"
    assert result.sections[1].content == "june body"
    assert result.markdown.index("sum body") < result.markdown.index("june body")
    assert result.usage.llm_calls == 2
    # per-section attribution stays exact via the per-unit wrapper
    assert [s.llm_calls for s in result.sections] == [1, 1]
    # progress events are emitted at submission, in section order
    running = [e for e in events if e.get("phase") == "running"]
    assert [e["section"] for e in running] == ["summary", "june-incidents"]


def test_parallel_preflight_call_cap_skips_all_sections():
    result = alchemy.run_goal(
        "report", REPORT_SPEC, corpus="c", tools=ConcurrencyTools(),
        llm=SectionKeyedLlm({}), budget=RunBudget(), concurrency=2,
        max_llm_calls=1)   # 1 < _MIN_UNIT_CALLS: nothing can run
    assert result.stop_reason == "call_cap"
    assert result.usage.llm_calls == 0
    assert not any(s.filled for s in result.sections)
    assert result.sections[0].note == "skipped: llm call cap"
    assert result.sections[1].note == "skipped: llm call cap"


def test_parallel_preflight_cancel_skips_all_sections():
    result = alchemy.run_goal(
        "report", REPORT_SPEC, corpus="c", tools=ConcurrencyTools(),
        llm=SectionKeyedLlm({}), budget=RunBudget(), concurrency=2,
        should_cancel=lambda: True)
    assert result.stop_reason == "cancelled"
    assert result.usage.llm_calls == 0
    # mirrors the sequential shape: first section wears the direct note
    assert result.sections[0].note == "cancelled"
    assert result.sections[1].note == "skipped: cancelled"


def test_parallel_quota_is_presplit_not_greedy():
    # cap=10, 2 sections: each unit gets quota max(2, 10//2)=5 upfront ->
    # max_rounds min(8, 5-1)=4 -> 4 search rounds + forced synthesis =
    # exactly 5 calls per unit, 10 total. A fast unit's unused quota is NOT
    # redistributed (accepted simplification; sequential keeps greedy).
    # max_handoffs=0 keeps round-capped units from spawning continuations
    # that would race the cap nondeterministically.
    class GreedySearcher:
        def __init__(self):
            self._lock = threading.Lock()
            self.calls = 0

        def complete(self, messages, tools):
            with self._lock:
                self.calls += 1
                n = self.calls
            if tools:
                return AssistantTurn(text=None, tool_calls=[
                    ToolCall(id=str(n), name="search",
                             arguments={"corpus": "c", "query": "q"})])
            return AssistantTurn(text="filled\n\nCONFIDENCE: low")

    result = alchemy.run_goal(
        "report", REPORT_SPEC, corpus="c", tools=ConcurrencyTools(),
        llm=GreedySearcher(), budget=RunBudget(), concurrency=2,
        max_llm_calls=10, max_handoffs=0)
    assert result.usage.llm_calls == 10
    assert [s.llm_calls for s in result.sections] == [5, 5]
    assert all(s.filled for s in result.sections)
    assert result.stop_reason == "final"   # filled via forced synthesis, no bubble
