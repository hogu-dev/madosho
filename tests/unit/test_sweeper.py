from datetime import datetime, timedelta, timezone

from madosho_server import db
from madosho_server.settings import Settings
from madosho_server.sweeper import sweep_stalled


def test_sweeps_rows_past_the_ceiling(tmp_path, monkeypatch):
    monkeypatch.setenv("MADOSHO_JOB_TIMEOUT", "600")
    db.configure_engine(f"sqlite:///{tmp_path/'sweep.db'}")
    db.create_all()
    now = datetime(2026, 6, 29, 12, 0, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    stale = now - timedelta(seconds=600 + 30 + 1)
    fresh = now - timedelta(seconds=10)
    with db.SessionLocal() as session:
        session.add(db.Document(id=1, filename="a", content_hash="h1",
                                file_uri="/a", mimetype="application/pdf",
                                status="indexing", updated_at=stale))
        session.add(db.Document(id=2, filename="b", content_hash="h2",
                                file_uri="/b", mimetype="application/pdf",
                                status="indexing", updated_at=fresh))
        session.commit()

        n = sweep_stalled(session, Settings.from_env(), now=now)

        assert n == 1
        assert session.get(db.Document, 1).status == "failed"
        assert session.get(db.Document, 2).status == "indexing"


def test_sweeps_pipeline_past_the_ceiling(tmp_path, monkeypatch):
    monkeypatch.setenv("MADOSHO_JOB_TIMEOUT", "600")
    db.configure_engine(f"sqlite:///{tmp_path/'sweep_pipe.db'}")
    db.create_all()
    now = datetime(2026, 6, 29, 12, 0, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    stale = now - timedelta(seconds=600 + 30 + 1)
    fresh = now - timedelta(seconds=10)
    with db.SessionLocal() as session:
        # Need a document to satisfy the pipeline FK. Pin its updated_at to
        # `fresh` so the assertion below (only the stale pipeline is swept)
        # never depends on the real wall clock: this doc is itself in a
        # sweepable status ("indexing"), so a server_default real-time
        # updated_at would otherwise tie its fate to the system clock.
        doc = db.Document(id=1, filename="c", content_hash="h3",
                          file_uri="/c", mimetype="application/pdf",
                          status="indexing", updated_at=fresh)
        session.add(doc)
        session.flush()
        session.add(db.Pipeline(id=1, document_id=doc.id, name="pipe-stale",
                                status="building", updated_at=stale))
        session.add(db.Pipeline(id=2, document_id=doc.id, name="pipe-fresh",
                                status="building", updated_at=fresh))
        session.commit()

        n = sweep_stalled(session, Settings.from_env(), now=now)

        assert n == 1
        assert session.get(db.Pipeline, 1).status == "failed"
        assert session.get(db.Pipeline, 2).status == "building"
