"""DbIngestReporter publishes phase/log/heartbeat to document.progress, and
count_pdf_pages is a best-effort, never-raising helper."""
import pytest

from madosho_server import db
from madosho_server.progress import DbIngestReporter, count_pdf_pages


@pytest.fixture
def doc_id(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path / 't.db'}")
    db.create_all()
    with db.SessionLocal() as s:
        c = db.Corpus(name="demo", config={"corpus": "demo", "query": []})
        s.add(c); s.flush()
        d = db.Document(filename="a.pdf", content_hash="h",
                        file_uri="u", mimetype="application/pdf", status="indexing")
        s.add(d); s.commit()
        return d.id


def _progress(document_id):
    with db.SessionLocal() as s:
        return s.get(db.Document, document_id).progress


def test_phase_and_log_are_published_to_the_row(doc_id):
    r = DbIngestReporter(db.SessionLocal, doc_id, page_count=42)
    r.phase("parsing")
    r.log("embedding 7 chunks")

    p = _progress(doc_id)
    assert p["phase"] == "parsing"
    assert p["page_count"] == 42
    assert "started_at" in p
    assert [e["msg"] for e in p["log"]] == ["parsing", "embedding 7 chunks"]


def test_heartbeat_appends_a_liveness_line_with_elapsed(doc_id):
    # settable clock so elapsed is deterministic (start at 0, advance to 90)
    now = {"t": 0.0}
    r = DbIngestReporter(db.SessionLocal, doc_id, clock=lambda: now["t"])
    r.phase("parsing")
    now["t"] = 90.0
    r._beat()   # one heartbeat tick (the thread would call this on a timer)

    log = _progress(doc_id)["log"]
    assert log[-1]["msg"] == "still working (parsing) - 90s elapsed"


def test_log_is_capped_to_avoid_unbounded_growth(doc_id):
    r = DbIngestReporter(db.SessionLocal, doc_id)
    for i in range(DbIngestReporter.MAX_LOG_LINES + 25):
        r.log(f"line {i}")
    log = _progress(doc_id)["log"]
    assert len(log) == DbIngestReporter.MAX_LOG_LINES
    assert log[-1]["msg"] == f"line {DbIngestReporter.MAX_LOG_LINES + 24}"   # newest kept


def test_context_manager_publishes_initial_state_and_stops_thread(doc_id):
    with DbIngestReporter(db.SessionLocal, doc_id, heartbeat_seconds=0.01) as r:
        assert _progress(doc_id)["phase"] == "starting"   # published on enter
    assert not r._thread.is_alive()                        # joined on exit


def test_count_pdf_pages_is_best_effort(tmp_path):
    assert count_pdf_pages("/whatever.txt", "text/plain") is None      # not a pdf
    assert count_pdf_pages(tmp_path / "missing.pdf", "application/pdf") is None  # unreadable -> None


def test_reporter_can_target_a_pipeline_row(doc_id):
    """Same machinery, pointed at the Pipeline row, drives the build console."""
    with db.SessionLocal() as s:
        d = s.get(db.Document, doc_id)
        p = db.Pipeline(document_id=d.id, name="p_fast",
                        config={}, collection="col", status="building")
        s.add(p); s.commit()
        pid = p.id
    r = DbIngestReporter(db.SessionLocal, pid, page_count=6, model=db.Pipeline)
    r.phase("extract")
    r.log("84 chunks")
    with db.SessionLocal() as s:
        prog = s.get(db.Pipeline, pid).progress
    assert prog["phase"] == "extract"
    assert prog["page_count"] == 6
    assert [e["msg"] for e in prog["log"]] == ["extract", "84 chunks"]
    # the document row must be untouched by a pipeline-targeted reporter
    assert _progress(doc_id) == {}
