# tests/unit/test_eval_proposal.py
"""Proposal = greedy winner + evidence, only if it beats baseline. The
proposed config must equal a config that was actually run (no cherry-picking)."""
from madosho_server import db
from madosho_server.eval import proposal, runner

BASELINE = {
    "corpus": "c",
    "ingest": {"parser": "docling", "chunker": "docling-hybrid",
               "embedder": "granite-embedding-english-r2",
               "store": {"qdrant": {"url": "http://q:6333"}}, "indexes": ["bm25", "dense"]},
    "query": ["keyword_search", "semantic_search", "fuse",
              {"rerank": {"model": "granite-reranker-english-r2", "top_k": 8}}],
}

GREEDY = {
    "baseline_score": 0.40, "final_score": 0.58,
    "path": [
        {"stage": "rerank", "label": "rerank top_k=12", "lift": 0.15, "score": 0.55,
         "candidate": {"stage": "rerank", "kind": "query", "op": "rerank",
                       "options": {"model": "granite-reranker-english-r2", "top_k": 12}}},
        {"stage": "embed", "label": "embedder=bge-small", "lift": 0.03, "score": 0.58,
         "candidate": {"stage": "embed", "kind": "ingest", "field": "embedder", "ref": "bge-small"}},
    ],
}


def test_compose_config_applies_every_locked_change():
    cfg = proposal.compose_config(BASELINE, GREEDY)
    assert cfg["ingest"]["embedder"] == "bge-small"
    rr = [s for s in cfg["query"] if isinstance(s, dict) and "rerank" in s][0]
    assert rr["rerank"]["top_k"] == 12
    # invariant: composing equals applying the same candidates through the runner
    expected = BASELINE
    for step in GREEDY["path"]:
        expected = runner.apply_candidate(expected, step["candidate"])
    assert cfg == expected


def test_build_proposal_when_winner_beats_baseline(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'p.db'}"); db.create_all()
    with db.SessionLocal() as s:
        c = db.Corpus(name="c", config=BASELINE); s.add(c); s.commit(); s.refresh(c)
        run = db.EvalRun(corpus_id=c.id, status="running", tokens_spent=1200, cost_actual=0.9)
        s.add(run); s.commit(); s.refresh(run)
        row = proposal.build_proposal(s, corpus_id=c.id, eval_run_id=run.id,
                                      baseline=BASELINE, greedy=GREEDY); s.commit()
        assert row is not None and row.status == "proposed"
        assert row.evidence["baseline"] == 0.40 and row.evidence["projected"] == 0.58
        assert len(row.evidence["lifts"]) == 2
        assert row.evidence["cost"]["tokens"] == 1200


def test_no_proposal_when_no_meaningful_win(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'p2.db'}"); db.create_all()
    with db.SessionLocal() as s:
        c = db.Corpus(name="c", config=BASELINE); s.add(c); s.commit(); s.refresh(c)
        run = db.EvalRun(corpus_id=c.id, status="running"); s.add(run); s.commit(); s.refresh(run)
        flat = {"baseline_score": 0.40, "final_score": 0.40, "path": []}
        row = proposal.build_proposal(s, corpus_id=c.id, eval_run_id=run.id,
                                      baseline=BASELINE, greedy=flat); s.commit()
        assert row is None


def test_dismiss_marks_dismissed(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'p4.db'}"); db.create_all()
    with db.SessionLocal() as s:
        c = db.Corpus(name="c", config=BASELINE); s.add(c); s.commit(); s.refresh(c)
        run = db.EvalRun(corpus_id=c.id, status="done"); s.add(run); s.commit(); s.refresh(run)
        row = proposal.build_proposal(s, corpus_id=c.id, eval_run_id=run.id,
                                      baseline=BASELINE, greedy=GREEDY); s.commit()
        proposal.dismiss_proposal(s, row.id); s.commit(); s.refresh(row)
        assert row.status == "dismissed" and row.decided_at is not None
