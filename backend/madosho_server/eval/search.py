# backend/madosho_server/eval/search.py
"""Scan then greedy-stack. The scan measures each stage's headroom against the
baseline (fills the cube). Greedy stacking builds the proposal: lock the best
single change, re-score the rest on top of it, stack the next best, repeat. Every
config scored is a real end-to-end run, so the final proposal is a complete
machine that was actually executed - never a glued composite of per-stage winners.

The runner must expose run_baseline(questions), run_candidate(candidate, questions)
(scoring on top of any locked changes), and lock(candidate)."""
from __future__ import annotations

import logging

PRIMARY = "mrr"
MIN_LIFT = 0.01     # tunable: marginal lift (absolute primary metric) to keep stacking
log = logging.getLogger("madosho_server.eval")


def _score(result: dict) -> float:
    return result["post"][PRIMARY]


def _try_candidate(runner, cand, questions):
    """Score one candidate, dropping it (returns None) if its pipeline errors - a
    failed candidate must not fail the whole run (spec section 9)."""
    try:
        return runner.run_candidate(cand, questions)
    except Exception:
        log.exception("eval candidate failed, dropping it: %s", cand.get("label"))
        return None


def scan(runner, plan: dict, questions: list) -> dict:
    """Score every stage's candidates against the (unstacked) baseline."""
    baseline = runner.run_baseline(questions)
    stages = {}
    for stage, candidates in plan.items():
        stages[stage] = [r for r in (_try_candidate(runner, c, questions)
                                     for c in candidates) if r is not None]
    return {"baseline": baseline, "stages": stages}


def greedy_stack(runner, plan: dict, questions: list, min_lift: float = MIN_LIFT) -> dict:
    """Lock the best change, re-score remaining stages on top, repeat."""
    baseline_score = _score(runner.run_baseline(questions))
    current = baseline_score
    remaining = dict(plan)                  # stage -> candidate list
    path = []
    while remaining:
        best = None                         # (lift, stage, candidate, score, result)
        for stage, candidates in remaining.items():
            for cand in candidates:
                res = _try_candidate(runner, cand, questions)
                if res is None:
                    continue
                lift = _score(res) - current
                if best is None or lift > best[0]:
                    best = (lift, stage, cand, _score(res), res)
        if best is None:                    # every remaining candidate errored
            break
        lift, stage, cand, score, res = best
        if lift < min_lift:
            break
        runner.lock(cand)                   # subsequent run_candidate scores on top
        path.append({"stage": stage, "label": cand["label"],
                     "score": score, "lift": round(lift, 4), "candidate": cand})
        current = score
        del remaining[stage]                # one change per stage in the chain
    return {"baseline_score": baseline_score, "final_score": current, "path": path}


def run_search(runner, plan: dict, questions: list, min_lift: float = MIN_LIFT) -> dict:
    """Scan (for the cube) + greedy stack (for the proposal), sharing the runner's
    trunk reuse. Run the scan first so locking during the stack does not perturb the
    per-stage-vs-baseline numbers the cube needs."""
    scan_result = scan(runner, plan, questions)
    greedy = greedy_stack(runner, plan, questions, min_lift=min_lift)
    return {"scan": scan_result, "greedy": greedy}
