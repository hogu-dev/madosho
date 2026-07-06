# tests/unit/test_research_worker.py
"""research_run model + execute_research worker logic.
Uses a sqlite DB and a fake run_agent so no Postgres/queue/LLM/subprocess is needed."""
from types import SimpleNamespace

from madosho_server import db
from madosho_server.research import execute_research
from madosho_server.settings import Settings


def _fresh_db(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'research.db'}")
    db.create_all()
    return db.SessionLocal


def _corpus(SessionLocal, name="rcorp"):
    with SessionLocal() as s:
        c = db.Corpus(name=name, config={})
        s.add(c)
        s.commit()
        s.refresh(c)
        return c.id


def test_research_run_round_trips(tmp_path):
    SessionLocal = _fresh_db(tmp_path)
    cid = _corpus(SessionLocal)
    with SessionLocal() as s:
        run = db.ResearchRun(
            corpus_id=cid, status="pending", prompt="how do sensors fail?",
            config={"source": "rag", "document_ids": [], "budget_chars": 100000,
                    "max_rounds": 8, "llm": {"provider": "openai", "model": "m"}},
            progress={"phase": "pending"})
        s.add(run)
        s.commit()
        s.refresh(run)
        rid = run.id
    with SessionLocal() as s:
        got = s.get(db.ResearchRun, rid)
        assert got.status == "pending"
        assert got.prompt == "how do sensors fail?"
        assert got.config["source"] == "rag"
        assert got.report_markdown is None
        assert got.citations == []
        assert got.run_log == []


def _settings(tmp_path):
    return Settings(database_url=f"sqlite:///{tmp_path/'research.db'}",
                    qdrant_url="http://q:6333", filestore_dir=str(tmp_path),
                    corpora_dir=str(tmp_path),
                    llm_api_key="k", llm_api_base="http://llm")


def _fake_report():
    # mimics research_agent.Report (markdown + dataclass citations + run_log + stop_reason)
    Cit = SimpleNamespace
    return SimpleNamespace(
        markdown="# Report\n\nFindings [doc1].",
        citations=[Cit(document_id=1, pipeline_id=2, pipeline="docling", position=0,
                       citation="doc1 p1", source="search", score=0.9, quote="...")],
        run_log=[{"round": 1, "kind": "tool_call", "name": "search"}],
        stop_reason="final")


def _make_run(SessionLocal, cid, **cfg):
    with SessionLocal() as s:
        run = db.ResearchRun(
            corpus_id=cid, status="pending", prompt="q?",
            config={"source": "rag", "document_ids": [], "budget_chars": 100000,
                    "max_rounds": 8, "llm": {"provider": "openai", "model": "m"}, **cfg},
            progress={"phase": "pending"})
        s.add(run)
        s.commit()
        s.refresh(run)
        return run.id


def test_execute_research_writes_report_and_marks_done(tmp_path, monkeypatch):
    SessionLocal = _fresh_db(tmp_path)
    cid = _corpus(SessionLocal)
    rid = _make_run(SessionLocal, cid)
    captured = {}

    def fake_run_agent(prompt, settings, provider, model, *, budget_chars, max_rounds,
                       research_run_id):
        captured["prompt"] = prompt
        captured["provider"] = provider
        captured["model"] = model
        return _fake_report()

    with SessionLocal() as s:
        execute_research(s, rid, _settings(tmp_path), run_agent=fake_run_agent)

    with SessionLocal() as s:
        got = s.get(db.ResearchRun, rid)
        assert got.status == "done"
        assert got.report_markdown.startswith("# Report")
        assert got.stop_reason == "final"
        assert got.citations[0]["document_id"] == 1   # dataclass -> dict via asdict
        assert got.run_log[0]["name"] == "search"
        assert got.progress["phase"] == "done"
        assert got.finished_at is not None
    # the composed prompt named the corpus and the provider/model threaded through
    assert "rcorp" in captured["prompt"]
    assert captured["provider"] == "openai" and captured["model"] == "m"


def test_execute_research_marks_failed_on_exception(tmp_path):
    SessionLocal = _fresh_db(tmp_path)
    cid = _corpus(SessionLocal)
    rid = _make_run(SessionLocal, cid)

    def boom(*a, **k):
        raise RuntimeError("llm exploded")

    with SessionLocal() as s:
        execute_research(s, rid, _settings(tmp_path), run_agent=boom)

    with SessionLocal() as s:
        got = s.get(db.ResearchRun, rid)
        assert got.status == "failed"
        assert "llm exploded" in (got.error or "")


def test_execute_research_rejects_missing_llm(tmp_path):
    SessionLocal = _fresh_db(tmp_path)
    cid = _corpus(SessionLocal)
    rid = _make_run(SessionLocal, cid, llm={})   # no provider/model

    called = {"n": 0}

    def fake_run_agent(*a, **k):
        called["n"] += 1
        return _fake_report()

    with SessionLocal() as s:
        execute_research(s, rid, _settings(tmp_path), run_agent=fake_run_agent)

    with SessionLocal() as s:
        got = s.get(db.ResearchRun, rid)
        assert got.status == "failed"
        assert "llm" in (got.error or "").lower()
    assert called["n"] == 0   # never invoked the agent


def test_execute_research_honours_cancel_set_during_run(tmp_path):
    """If a cancel is written during the run (simulating an external API call),
    the worker should finish with status 'cancelled', not 'done'."""
    SessionLocal = _fresh_db(tmp_path)
    cid = _corpus(SessionLocal)
    rid = _make_run(SessionLocal, cid)

    def cancelling_run_agent(prompt, settings, provider, model, *, budget_chars, max_rounds,
                             research_run_id):
        # simulate an external cancel arriving while the agent is working
        with SessionLocal() as s2:
            row = s2.get(db.ResearchRun, rid)
            row.status = "cancelled"
            s2.commit()
        return _fake_report()

    with SessionLocal() as s:
        execute_research(s, rid, _settings(tmp_path), run_agent=cancelling_run_agent)

    with SessionLocal() as s:
        got = s.get(db.ResearchRun, rid)
        assert got.status == "cancelled"
        assert got.finished_at is not None
        # The agent finished its work before the cancel was observed, so the
        # report it produced must be persisted - the flush() before the
        # cancel-check (and the expire_all() inside it) must not discard it.
        assert got.report_markdown is not None
        assert got.report_markdown.startswith("# Report")


def test_run_research_task_is_registered():
    from madosho_server import tasks
    names = {t.name for t in tasks.app.tasks.values()}
    assert "run_research" in names


def test_worker_consumes_research_queue(monkeypatch):
    from madosho_server.entrypoints import worker_queues
    monkeypatch.delenv("MADOSHO_WORKER_QUEUES", raising=False)
    assert "research" in worker_queues()
