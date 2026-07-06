# tests/unit/test_eval_search.py
"""Scan then greedy-stack. The proposal is always a config that was run
as one machine; the greedy winner stacks changes whose marginal lift clears the
threshold. Re-scoring on top of a locked winner is what makes this stacking and
not just the scan (a stage's value can change after an upstream improvement)."""
from madosho_server.eval import search


class _FakeRunner:
    """Deterministic scores keyed by the frozenset of applied candidate labels.
    Models a corpus where rerank helps a lot, then embed adds a little on top."""
    SCORES = {
        frozenset(): 0.40,                                  # baseline
        frozenset({"rerank top_k=12"}): 0.55,
        frozenset({"semantic k=100"}): 0.42,
        frozenset({"embedder=bge-small"}): 0.41,
        frozenset({"rerank top_k=12", "embedder=bge-small"}): 0.58,
        frozenset({"rerank top_k=12", "semantic k=100"}): 0.55,
    }

    def __init__(self):
        self.baseline = {"ingest": {}, "query": []}
        self.applied = []          # accumulates locked candidates (for stacking)

    def _score(self, extra_labels):
        key = frozenset({*(c["label"] for c in self.applied), *extra_labels})
        return self.SCORES.get(key, 0.40)

    def run_baseline(self, questions):
        return {"label": "baseline", "post": {"mrr": self._score(set())}}

    def run_candidate(self, candidate, questions):
        return {"label": candidate["label"], "stage": candidate["stage"],
                "post": {"mrr": self._score({candidate["label"]})}}

    def lock(self, candidate):
        self.applied.append(candidate)


PLAN = {
    "rerank": [{"stage": "rerank", "label": "rerank top_k=12", "kind": "query"}],
    "semantic": [{"stage": "semantic", "label": "semantic k=100", "kind": "query"}],
    "embed": [{"stage": "embed", "label": "embedder=bge-small", "kind": "ingest"}],
}


def test_scan_scores_every_candidate_against_baseline():
    r = _FakeRunner()
    out = search.scan(r, PLAN, questions=[{}])
    assert out["baseline"]["post"]["mrr"] == 0.40
    labels = {c["label"]: c["post"]["mrr"] for stage in out["stages"].values() for c in stage}
    assert labels["rerank top_k=12"] == 0.55
    assert labels["semantic k=100"] == 0.42


def test_greedy_stack_locks_best_then_restacks():
    r = _FakeRunner()
    result = search.greedy_stack(r, PLAN, questions=[{}], min_lift=0.01)
    # rerank wins first (0.55 vs 0.40); then embed adds on top (0.58 vs 0.55);
    # semantic never clears the threshold and is dropped.
    chain = [step["label"] for step in result["path"]]
    assert chain == ["rerank top_k=12", "embedder=bge-small"]
    assert result["baseline_score"] == 0.40
    assert result["final_score"] == 0.58


def test_greedy_stack_stops_when_no_lift_clears_threshold():
    r = _FakeRunner()
    flat_plan = {"semantic": PLAN["semantic"]}    # only a candidate that barely moves (0.42)
    result = search.greedy_stack(r, flat_plan, questions=[{}], min_lift=0.05)
    assert result["path"] == []                   # 0.42 - 0.40 = 0.02 < 0.05
    assert result["final_score"] == result["baseline_score"] == 0.40


def test_run_search_returns_scan_and_greedy_together():
    r = _FakeRunner()
    out = search.run_search(r, PLAN, questions=[{}], min_lift=0.01)
    assert "scan" in out and "greedy" in out
    assert out["greedy"]["final_score"] == 0.58
