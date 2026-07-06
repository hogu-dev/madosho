# tests/integration/test_postgres.py
from uuid import uuid4

import procrastinate
import pytest
from sqlalchemy import text

from madosho_server import db, init_db, tasks
from madosho_server.settings import pg_conninfo

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def stack():
    """Start Postgres once; apply schema once (procrastinate schema is apply-once);
    select the defer-only sync connector; open the app for the whole module."""
    from testcontainers.postgres import PostgresContainer
    # psycopg v3 driver in the URL so SQLAlchemy uses postgresql+psycopg://
    with PostgresContainer("postgres:17", driver="psycopg") as pg:
        url = pg.get_connection_url()
        db.configure_engine(url)
        init_db.init_database(url)                 # app tables + procrastinate tables (once)
        tasks.use_connector(procrastinate.SyncPsycopgConnector(conninfo=pg_conninfo(url)))
        with tasks.app.open():
            yield url


@pytest.fixture()
def corpus_id(stack):
    """A fresh, uniquely-named corpus per test (corpus.name is UNIQUE)."""
    with db.SessionLocal() as s:
        corpus = db.Corpus(name=f"demo-{uuid4().hex[:8]}", config={"corpus": "demo", "query": []})
        s.add(corpus); s.commit(); s.refresh(corpus)
        return corpus.id


def _job_count() -> int:
    with db.engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM procrastinate_jobs")).scalar_one()


def test_init_database_is_idempotent(stack):
    # `stack` already applied the schema once. The compose `init` one-shot re-runs
    # on every `docker compose up`, so a second init_database() must be a clean
    # no-op — procrastinate's schema is apply-once and would otherwise raise
    # "relation already exists", failing the init container.
    init_db.init_database(stack)                # must not raise on re-run
    assert _job_count() >= 0                     # procrastinate tables still intact


def _enqueue_in_txn(session, doc):
    session.add(doc)
    session.flush()
    raw = session.connection().connection.driver_connection
    tasks.ingest_document.configure(connection=raw).defer(document_id=doc.id)


def test_rollback_leaves_no_row_and_no_job(corpus_id):
    before = _job_count()
    with db.SessionLocal() as s:
        doc = db.Document(corpus_id=corpus_id, filename="r.txt", content_hash="rollback-hash",
                          file_uri="x", mimetype="text/plain", status="received")
        _enqueue_in_txn(s, doc)
        s.rollback()
    with db.SessionLocal() as s:
        assert s.query(db.Document).filter_by(content_hash="rollback-hash").count() == 0
    assert _job_count() == before              # job did NOT persist


def test_commit_persists_row_and_job(corpus_id):
    before = _job_count()
    with db.SessionLocal() as s:
        doc = db.Document(corpus_id=corpus_id, filename="c.txt", content_hash="commit-hash",
                          file_uri="x", mimetype="text/plain", status="received")
        _enqueue_in_txn(s, doc)
        s.commit()
    with db.SessionLocal() as s:
        assert s.query(db.Document).filter_by(content_hash="commit-hash").count() == 1
    assert _job_count() == before + 1          # row AND job persisted together
