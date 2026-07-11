"""Stage E: concurrency safety for the alchemy engine.

The fakes here are deliberately NOT order-keyed (no pop(0)): once two units
run at the same time, call order is meaningless, so scripted replies key off
prompt CONTENT and synchronization primitives (Barrier/Event) pin the
interleavings the tests need to prove.
"""
import threading
import time

from alchemy.llm import CallCapExceeded, CountingLlm
from research_agent.types import AssistantTurn


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
