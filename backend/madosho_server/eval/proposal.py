# backend/madosho_server/eval/proposal.py
"""Compose the greedy winner into a config_proposal and own the dismiss transition.
The proposal is a READ-ONLY recommendation: it records the best-scoring recipe an
eval run found (and the projected lift) so the UI can surface it. Adopting it is a
manual step -- the operator builds that recipe as a pipeline on the document and
sets it effective; there is no auto-apply (retrieval resolves through per-document
pipelines, not the corpus config a build-then-swap would have repointed).

No-cherry-pick invariant: the proposed config is the baseline with exactly the
locked greedy changes applied, which is a pipeline that was actually run end to
end (compose_config replays the same apply_candidate the runner used)."""
from __future__ import annotations

from sqlalchemy import func

from madosho_server import db
from madosho_server.eval.runner import apply_candidate


def compose_config(baseline: dict, greedy: dict) -> dict:
    cfg = baseline
    for step in greedy["path"]:
        cfg = apply_candidate(cfg, step["candidate"])
    return cfg


def build_proposal(session, corpus_id: int, eval_run_id: int,
                   baseline: dict, greedy: dict) -> "db.ConfigProposal | None":
    if not greedy["path"] or greedy["final_score"] <= greedy["baseline_score"]:
        return None
    run = session.get(db.EvalRun, eval_run_id)
    evidence = {
        "baseline": greedy["baseline_score"],
        "projected": greedy["final_score"],
        "lifts": [{"stage": s["stage"], "label": s["label"], "lift": s["lift"]}
                  for s in greedy["path"]],
        "cost": {"tokens": (run.tokens_spent if run else 0),
                 "dollars": (run.cost_actual if run else None)},
    }
    row = db.ConfigProposal(corpus_id=corpus_id, eval_run_id=eval_run_id,
                            proposed_config=compose_config(baseline, greedy),
                            evidence=evidence, status="proposed")
    session.add(row)
    session.flush()
    return row


def dismiss_proposal(session, proposal_id: int) -> None:
    row = session.get(db.ConfigProposal, proposal_id)
    if row is None or row.status != "proposed":
        return
    row.status = "dismissed"
    row.decided_at = func.now()
