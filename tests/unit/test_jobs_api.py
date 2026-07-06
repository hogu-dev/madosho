"""GET /jobs -- the global activity feed. Every build is a Pipeline row, so the
feed is pipelines joined to their document: default pipelines read as kind=ingest,
the rest as kind=build. Running jobs always show; finished ones are capped."""
from fastapi.testclient import TestClient

from madosho_server import api, db


def _client(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'jobs.db'}")
    db.create_all()
    return TestClient(api.app)


def _doc(session, filename, status="indexed"):
    d = db.Document(filename=filename, content_hash=filename, file_uri=f"/{filename}",
                    mimetype="application/pdf", status=status)
    session.add(d)
    session.flush()
    return d


def _pipe(session, doc_id, name, status, is_default=False, progress=None, error=None):
    p = db.Pipeline(document_id=doc_id, name=name, status=status, is_default=is_default,
                    progress=progress or {}, error=error)
    session.add(p)
    session.flush()
    return p


def test_jobs_maps_default_to_ingest_and_others_to_build(tmp_path):
    client = _client(tmp_path)
    try:
        with db.SessionLocal() as s:
            doc = _doc(s, "f35.pdf")
            _pipe(s, doc.id, "f35", status="indexed", is_default=True)        # ingest
            _pipe(s, doc.id, "f35_vision", status="building")                 # build
            s.commit()
        jobs = client.get("/jobs").json()
        by_name = {j["name"]: j for j in jobs}
        assert by_name["f35"]["kind"] == "ingest"
        assert by_name["f35"]["document_filename"] == "f35.pdf"
        assert by_name["f35_vision"]["kind"] == "build"
        assert by_name["f35_vision"]["status"] == "building"
    finally:
        api.app.dependency_overrides.clear()


def test_jobs_keeps_all_running_but_caps_finished(tmp_path):
    client = _client(tmp_path)
    try:
        with db.SessionLocal() as s:
            doc = _doc(s, "big.pdf")
            for i in range(api.JOBS_TERMINAL_LIMIT + 5):                      # over the cap
                _pipe(s, doc.id, f"done_{i}", status="indexed")
            for i in range(3):                                               # always-shown
                _pipe(s, doc.id, f"live_{i}", status="building")
            s.commit()
        jobs = client.get("/jobs").json()
        running = [j for j in jobs if j["status"] == "building"]
        finished = [j for j in jobs if j["status"] != "building"]
        assert len(running) == 3                                            # never capped
        assert len(finished) == api.JOBS_TERMINAL_LIMIT                     # capped
    finally:
        api.app.dependency_overrides.clear()


def test_jobs_newest_first(tmp_path):
    client = _client(tmp_path)
    try:
        with db.SessionLocal() as s:
            doc = _doc(s, "a.pdf")
            _pipe(s, doc.id, "first", status="indexed")
            _pipe(s, doc.id, "second", status="indexed")
            _pipe(s, doc.id, "third", status="indexed")
            s.commit()
        names = [j["name"] for j in client.get("/jobs").json()]
        # same created_at on SQLite -> id desc tiebreak keeps the most-recent insert on top
        assert names.index("third") < names.index("first")
    finally:
        api.app.dependency_overrides.clear()


def test_jobs_empty_when_no_pipelines(tmp_path):
    client = _client(tmp_path)
    try:
        assert client.get("/jobs").json() == []
    finally:
        api.app.dependency_overrides.clear()
