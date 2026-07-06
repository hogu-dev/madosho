"""The three eval tables round-trip through the JSON-on-SQLite path."""
from madosho_server import db


def _corpus(session, name="c"):
    c = db.Corpus(name=name, config={"corpus": name, "query": []})
    session.add(c); session.commit(); session.refresh(c)
    return c


def test_eval_run_roundtrip(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'er.db'}"); db.create_all()
    with db.SessionLocal() as s:
        c = _corpus(s)
        run = db.EvalRun(corpus_id=c.id, status="pending",
                         progress={"phase": "golden", "done": 0, "total": 10},
                         sampling={"doc_ids": [1, 2], "questions_per_doc": 3},
                         candidate_plan={"rerank": [{"label": "top_k=8"}]},
                         token_budget=50000, cost_estimate=1.2)
        s.add(run); s.commit(); s.refresh(run)
        got = s.get(db.EvalRun, run.id)
        assert got.status == "pending"
        assert got.progress["phase"] == "golden"
        assert got.candidate_plan["rerank"][0]["label"] == "top_k=8"
        assert got.tokens_spent == 0 and got.results is None
        assert got.ephemeral_collections == []   # default empty list


def test_eval_question_roundtrip(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'eq.db'}"); db.create_all()
    with db.SessionLocal() as s:
        c = _corpus(s)
        doc = db.Document(filename="f.pdf", content_hash="h",
                          file_uri="u", mimetype="application/pdf")
        s.add(doc); s.commit(); s.refresh(doc)
        run = db.EvalRun(corpus_id=c.id, status="running")
        s.add(run); s.commit(); s.refresh(run)
        q = db.EvalQuestion(eval_run_id=run.id, document_id=doc.id,
                            question="What is the notice period?",
                            answer_chunk_refs=["c1"], source_chunk_text="ninety days notice",
                            quality={"critic": "kept", "score": 0.8})
        s.add(q); s.commit()
        got = s.query(db.EvalQuestion).one()
        assert got.answer_chunk_refs == ["c1"]
        assert got.source_chunk_text.startswith("ninety")


def test_config_proposal_roundtrip(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'cp.db'}"); db.create_all()
    with db.SessionLocal() as s:
        c = _corpus(s)
        run = db.EvalRun(corpus_id=c.id, status="done")
        s.add(run); s.commit(); s.refresh(run)
        p = db.ConfigProposal(corpus_id=c.id, eval_run_id=run.id,
                              proposed_config={"corpus": "c", "ingest": {}, "query": []},
                              evidence={"baseline": 0.41, "projected": 0.58,
                                        "lifts": [{"stage": "rerank", "lift": 0.17}]},
                              status="proposed")
        s.add(p); s.commit(); s.refresh(p)
        got = s.get(db.ConfigProposal, p.id)
        assert got.status == "proposed" and got.evidence["projected"] == 0.58
        assert got.approver is None and got.decided_at is None
