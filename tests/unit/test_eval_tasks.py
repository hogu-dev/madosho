# tests/unit/test_eval_tasks.py
"""The eval orchestration ties golden -> search -> cube -> proposal,
checks cancellation between phases, and cleans up ephemeral collections. Fakes
stand in for the LLM and the corpus opener so no models or Qdrant are needed."""
from madosho.core.types import Chunk, Hit
from madosho_server import db, membership, tasks
from madosho_server.settings import Settings


def _settings(tmp_path):
    return Settings(database_url="sqlite://", qdrant_url="http://q:6333",
                    filestore_dir=str(tmp_path / "fs"), corpora_dir=str(tmp_path / "co"))


class _FakeCorpus:
    """Returns the answer chunk first for any query, so retrieval always scores 1.0."""
    def __init__(self, collection=None):
        self.collection = collection
        self.indexed = 0

    def parse_file(self, sf):
        return object()

    def index_document(self, doc):
        self.indexed += 1

    def query(self, text):
        ch = Chunk(id="k", doc_id="d", text="The deposit is refundable within thirty days.",
                   position=0, page=1)
        return [Hit(chunk_id="k", score=1.0, source_index="rrf", chunk=ch)]


def _seed(tmp_path, sampling=None):
    db.configure_engine(f"sqlite:///{tmp_path/'t.db'}"); db.create_all()
    (tmp_path / "fs").mkdir(parents=True, exist_ok=True)
    with db.SessionLocal() as s:
        cfg = {"corpus": "c", "ingest": {"parser": "p", "chunker": "ch", "embedder": "e",
               "store": {"qdrant": {"url": "http://q:6333"}}, "indexes": ["bm25", "dense"]},
               "query": ["keyword_search", "semantic_search", "fuse",
                         {"rerank": {"model": "rr", "top_k": 8}}]}
        c = db.Corpus(name="c", config=cfg); s.add(c); s.commit(); s.refresh(c)
        doc = db.Document(filename="f.pdf", content_hash="h", file_uri="h/f.pdf",
                          mimetype="application/pdf", status="indexed",
                          traits={"doc_type": "plain"},
                          artifacts={"chunks": [{"id": "k",
                              "text": "The deposit is refundable within thirty days of move-out."}]})
        s.add(doc); s.commit(); s.refresh(doc)
        membership.add_membership(s, doc.id, c.id); s.commit()
        run = db.EvalRun(corpus_id=c.id, status="pending",
                         sampling=sampling or {"n_docs": 1, "questions_per_doc": 3},
                         candidate_plan={})
        s.add(run); s.commit(); s.refresh(run)
        return c.id, run.id


def _registry():
    return {"chunker": [{"name": "fixed-window", "origin_tier": "us_src", "hardware": "cpu"}],
            "embedder": [{"name": "bge-small", "origin_tier": "us_src", "hardware": "cpu"}],
            "reranker": []}


def test_execute_run_happy_path_writes_cube_and_finishes(tmp_path, monkeypatch):
    cid, rid = _seed(tmp_path)
    monkeypatch.setattr(tasks.FileStore, "path_for", lambda self, uri: tmp_path / "fs" / "f.pdf")
    (tmp_path / "fs" / "f.pdf").write_bytes(b"%PDF-1.4 fake")
    with db.SessionLocal() as s:
        tasks.execute_run(s, rid, _settings(tmp_path),
                          llm=lambda prompt: "When is the deposit refundable?",
                          opener=lambda cfg, coll: _FakeCorpus(coll),
                          list_registry=_registry,
                          drop_collection=lambda name: None)
        run = s.get(db.EvalRun, rid)
        assert run.status == "done" and run.progress["phase"] == "done"
        assert s.query(db.EvalQuestion).filter_by(eval_run_id=rid).count() == 1
        # f-empirical cells were written
        assert s.query(db.TechniqueRating).filter_by(source="f-empirical").count() >= 1


def test_execute_run_preserves_partial_results_on_cancel(tmp_path, monkeypatch):
    cid, rid = _seed(tmp_path)
    monkeypatch.setattr(tasks.FileStore, "path_for", lambda self, uri: tmp_path / "fs" / "f.pdf")
    (tmp_path / "fs" / "f.pdf").write_bytes(b"%PDF-1.4 fake")

    # cancel the run as soon as the golden set is built: the llm callback flips status.
    def cancelling_llm(prompt):
        with db.SessionLocal() as s2:
            r = s2.get(db.EvalRun, rid); r.status = "cancelled"; s2.commit()
        return "When is the deposit refundable?"

    with db.SessionLocal() as s:
        tasks.execute_run(s, rid, _settings(tmp_path), llm=cancelling_llm,
                          opener=lambda cfg, coll: _FakeCorpus(coll),
                          list_registry=_registry, drop_collection=lambda name: None)
        run = s.get(db.EvalRun, rid)
        assert run.status == "cancelled"
        assert run.finished_at is not None
        # partial: the golden questions survived
        assert s.query(db.EvalQuestion).filter_by(eval_run_id=rid).count() == 1


def test_execute_run_records_error_on_failure(tmp_path, monkeypatch):
    cid, rid = _seed(tmp_path)
    monkeypatch.setattr(tasks.FileStore, "path_for", lambda self, uri: tmp_path / "fs" / "f.pdf")
    (tmp_path / "fs" / "f.pdf").write_bytes(b"x")

    def boom(prompt):
        raise RuntimeError("provider down")

    with db.SessionLocal() as s:
        tasks.execute_run(s, rid, _settings(tmp_path), llm=boom,
                          opener=lambda cfg, coll: _FakeCorpus(coll),
                          list_registry=_registry, drop_collection=lambda name: None)
        run = s.get(db.EvalRun, rid)
        assert run.status == "failed" and "provider down" in (run.error or "")
        assert run.finished_at is not None


def test_run_eval_task_invokes_execute_run(tmp_path, monkeypatch):
    cid, rid = _seed(tmp_path, sampling={"n_docs": 1, "questions_per_doc": 1,
                                         "llm": {"provider": "openai", "model": "fake"}})
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'t.db'}")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("QDRANT_URL", "http://q:6333")
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "co"))

    called = {}
    def fake_execute(session, run_id, settings, *, llm, **kw):
        called["run_id"] = run_id
        called["provider_model"] = (llm.provider, llm.model)
    monkeypatch.setattr(tasks, "execute_run", fake_execute)

    tasks.run_eval(rid)
    assert called["run_id"] == rid
    assert called["provider_model"] == ("openai", "fake")


def test_eval_llm_counts_tokens(monkeypatch):
    from types import SimpleNamespace
    from madosho_server.settings import Settings
    settings = Settings(database_url="sqlite://", qdrant_url="x", filestore_dir="x", corpora_dir="x")

    def fake_complete(messages, provider, model, settings, stream=False):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="a question?"))],
            usage=SimpleNamespace(total_tokens=42))
    monkeypatch.setattr(tasks, "complete", fake_complete)

    llm = tasks._eval_llm(settings, "openai", "fake")
    assert llm("prompt") == "a question?"
    assert llm.tokens == 42

