import procrastinate
from fastapi.testclient import TestClient

from madosho_server import api, db, tasks


def _setup(tmp_path, monkeypatch):
    """Wire env + SQLite + in-memory queue + stubbed enqueue; return the recorded list."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))
    tasks.use_connector(procrastinate.testing.InMemoryConnector())
    enqueued: list[int] = []
    api.app.dependency_overrides[api.get_enqueue] = lambda: (lambda s, did: enqueued.append(did))
    return enqueued


def test_create_corpus_upload_and_status(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))

    # in-memory queue so the lifespan's app.open() needs no Postgres
    tasks.use_connector(procrastinate.testing.InMemoryConnector())
    # stub the transactional enqueue (the real path needs psycopg/Postgres — Task 13)
    enqueued: list[int] = []
    api.app.dependency_overrides[api.get_enqueue] = lambda: (lambda s, did: enqueued.append(did))

    try:
        with TestClient(api.app) as client:
            r = client.post("/corpora", json={"name": "demo"})
            assert r.status_code == 201
            corpus_id = r.json()["id"]

            files = {"file": ("a.txt", b"hello world", "text/plain")}
            r = client.post(f"/corpora/{corpus_id}/documents", files=files)
            assert r.status_code == 202
            body = r.json()
            assert body["status"] == "received"
            assert enqueued == [body["id"]]      # enqueue called once with the doc id

            r = client.get(f"/documents/{body['id']}")
            assert r.status_code == 200
            assert r.json()["status"] == "received"
    finally:
        api.app.dependency_overrides.clear()


def test_delete_document_removes_row_children_and_enqueues_cleanup(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cleaned: list[tuple] = []
    api.app.dependency_overrides[api.get_enqueue_delete] = (
        lambda: (lambda s, collections, uri: cleaned.append((collections, uri))))
    try:
        with TestClient(api.app) as client:
            corpus_id = client.post("/corpora", json={"name": "demo"}).json()["id"]
            files = {"file": ("a.txt", b"hello world", "text/plain")}
            did = client.post(f"/corpora/{corpus_id}/documents", files=files).json()["id"]
            # seed a child row that FKs to the document (the rating cube writes these);
            # Postgres would reject the delete if it lingered.
            with db.SessionLocal() as s:
                s.add(db.TechniqueRating(corpus_id=corpus_id, document_id=did,
                                         dimension="chunk", score=3.0, source="static"))
                s.commit()

            with db.SessionLocal() as s:
                doc_file_uri = s.get(db.Document, did).file_uri
            assert client.delete(f"/documents/{did}").status_code == 204
            assert client.get(f"/documents/{did}").status_code == 404      # row is gone
            assert cleaned                                                  # cleanup deferred
            assert isinstance(cleaned[0][0], list)                         # collections list
            assert cleaned[0][1] == doc_file_uri                           # correct file_uri
            with db.SessionLocal() as s:
                assert s.query(db.TechniqueRating).filter_by(document_id=did).count() == 0
    finally:
        api.app.dependency_overrides.clear()


def test_delete_document_clears_corpus_pipeline_pins(tmp_path, monkeypatch):
    """A document with a per-corpus pipeline pin (a document_corpus_pipeline row) must
    still delete. That table has a real FK on document_id, so a lingering pin row makes
    Postgres reject the delete with a ForeignKeyViolation (a 500). SQLite here does not
    enforce FKs, so we assert the pin rows are actually gone rather than trusting the
    status code alone -- that is what catches the regression on either backend."""
    _setup(tmp_path, monkeypatch)
    api.app.dependency_overrides[api.get_enqueue_delete] = (
        lambda: (lambda s, collections, uri: None))
    try:
        with TestClient(api.app) as client:
            corpus_id = client.post("/corpora", json={"name": "demo"}).json()["id"]
            files = {"file": ("a.txt", b"hello world", "text/plain")}
            did = client.post(f"/corpora/{corpus_id}/documents", files=files).json()["id"]
            # pin a pipeline for this (corpus, document); pipeline_id is a plain int
            # with no FK, so a bare id stands in for a real pipeline.
            with db.SessionLocal() as s:
                s.add(db.DocumentCorpusPipeline(corpus_id=corpus_id, document_id=did,
                                                pipeline_id=1234))
                s.commit()

            assert client.delete(f"/documents/{did}").status_code == 204
            with db.SessionLocal() as s:
                assert s.query(db.DocumentCorpusPipeline).filter_by(document_id=did).count() == 0
    finally:
        api.app.dependency_overrides.clear()


def test_document_file_forces_download_for_unsafe_types(tmp_path, monkeypatch):
    """An uploaded text/html must not be served inline (stored-XSS vector): it is
    forced to download, with nosniff so it can't be MIME-sniffed into HTML."""
    _setup(tmp_path, monkeypatch)
    try:
        with TestClient(api.app) as client:
            cid = client.post("/corpora", json={"name": "demo"}).json()["id"]
            files = {"file": ("evil.html", b"<script>alert(1)</script>", "text/html")}
            did = client.post(f"/corpora/{cid}/documents", files=files).json()["id"]
            r = client.get(f"/documents/{did}/file")
            assert r.status_code == 200
            assert r.headers["content-disposition"].startswith("attachment")
            assert r.headers["x-content-type-options"] == "nosniff"
    finally:
        api.app.dependency_overrides.clear()


def test_document_file_renders_pdf_inline(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        with TestClient(api.app) as client:
            cid = client.post("/corpora", json={"name": "demo"}).json()["id"]
            files = {"file": ("a.pdf", b"%PDF-1.4 minimal", "application/pdf")}
            did = client.post(f"/corpora/{cid}/documents", files=files).json()["id"]
            r = client.get(f"/documents/{did}/file")
            assert r.headers["content-disposition"].startswith("inline")
            assert r.headers["x-content-type-options"] == "nosniff"
    finally:
        api.app.dependency_overrides.clear()


def test_delete_missing_document_returns_404(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        with TestClient(api.app) as client:
            assert client.delete("/documents/999").status_code == 404
    finally:
        api.app.dependency_overrides.clear()


def test_create_corpus_rejects_invalid_name(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        with TestClient(api.app) as client:
            r = client.post("/corpora", json={"name": "has spaces"})
            assert r.status_code == 422          # rejected at the boundary
    finally:
        api.app.dependency_overrides.clear()


def test_create_corpus_duplicate_returns_409(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        with TestClient(api.app) as client:
            assert client.post("/corpora", json={"name": "dup"}).status_code == 201
            r = client.post("/corpora", json={"name": "dup"})
            assert r.status_code == 409
    finally:
        api.app.dependency_overrides.clear()


def test_upload_is_idempotent(tmp_path, monkeypatch):
    enqueued = _setup(tmp_path, monkeypatch)
    try:
        with TestClient(api.app) as client:
            cid = client.post("/corpora", json={"name": "demo"}).json()["id"]
            files = {"file": ("a.txt", b"same bytes", "text/plain")}
            r1 = client.post(f"/corpora/{cid}/documents", files=files)
            files = {"file": ("a.txt", b"same bytes", "text/plain")}
            r2 = client.post(f"/corpora/{cid}/documents", files=files)
            assert r1.status_code == 202 and r2.status_code == 202
            assert r1.json()["id"] == r2.json()["id"]   # same doc, deduped by content hash
            assert enqueued == [r1.json()["id"]]          # enqueued exactly once
    finally:
        api.app.dependency_overrides.clear()


def test_list_corpora_and_documents(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        with TestClient(api.app) as client:
            client.post("/corpora", json={"name": "alpha"})
            cid = client.post("/corpora", json={"name": "beta"}).json()["id"]
            client.post(f"/corpora/{cid}/documents",
                        files={"file": ("a.txt", b"hi", "text/plain")})

            r = client.get("/corpora")
            assert r.status_code == 200
            names = {c["name"] for c in r.json()}
            assert {"alpha", "beta"} <= names

            r = client.get(f"/corpora/{cid}/documents")
            assert r.status_code == 200
            assert [d["filename"] for d in r.json()] == ["a.txt"]

            assert client.get("/corpora/99999/documents").status_code == 404
    finally:
        api.app.dependency_overrides.clear()


def test_unknown_corpus_and_document_404(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        with TestClient(api.app) as client:
            files = {"file": ("a.txt", b"x", "text/plain")}
            assert client.post("/corpora/999/documents", files=files).status_code == 404
            assert client.get("/documents/999").status_code == 404
    finally:
        api.app.dependency_overrides.clear()


def test_document_artifacts_export(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        with TestClient(api.app) as client:
            cid = client.post("/corpora", json={"name": "art"}).json()["id"]
            did = client.post(f"/corpora/{cid}/documents",
                              files={"file": ("a.txt", b"hi", "text/plain")}).json()["id"]
            # before indexing: artifacts is None -> 409 honest edge
            assert client.get(f"/documents/{did}/artifacts").status_code == 409

            with db.SessionLocal() as s:
                d = s.get(db.Document, did)
                d.status = "indexed"
                d.kernel_doc_id = "k1"
                d.artifacts = {"doc_id": "k1",
                               "chunks": [{"id": "c1", "doc_id": "k1", "text": "hello",
                                           "position": 0, "page": 1, "metadata": {}}],
                               "blocks": [{"kind": "table", "content": "| a |",
                                           "provenance": {"source": "a.txt", "page": 1, "bbox": None}},
                                          {"kind": "text", "content": "hello",
                                           "provenance": {"source": "a.txt", "page": 1, "bbox": None}}]}
                s.commit()

            r = client.get(f"/documents/{did}/artifacts")
            assert r.status_code == 200
            body = r.json()
            assert body["document_id"] == did
            assert body["chunks"][0]["text"] == "hello"
            assert len(body["tables"]) == 1          # only TABLE blocks surface as tables
            assert body["tables"][0]["content"] == "| a |"

            assert client.get("/documents/99999/artifacts").status_code == 404
    finally:
        api.app.dependency_overrides.clear()


def test_update_config_and_rebuild(tmp_path, monkeypatch):
    enqueued = _setup(tmp_path, monkeypatch)
    try:
        with TestClient(api.app) as client:
            cid = client.post("/corpora", json={"name": "cfg"}).json()["id"]
            did = client.post(f"/corpora/{cid}/documents",
                              files={"file": ("a.txt", b"hi", "text/plain")}).json()["id"]
            enqueued.clear()  # ignore the upload's enqueue

            corpus = next(c for c in client.get("/corpora").json() if c["id"] == cid)
            new_cfg = corpus["config"]
            new_cfg["ingest"]["chunker"] = "sentence"
            r = client.put(f"/corpora/{cid}/config", json={"config": new_cfg})
            assert r.status_code == 200
            assert r.json()["config"]["ingest"]["chunker"] == "sentence"

            assert client.put(f"/corpora/{cid}/config", json={"config": {"bad": 1}}).status_code == 422

            r = client.post(f"/corpora/{cid}/rebuild")
            assert r.status_code == 202
            assert r.json()["rebuilding"] == 1
            assert enqueued == [did]

            assert client.post("/corpora/99999/rebuild").status_code == 404
    finally:
        api.app.dependency_overrides.clear()


def test_components_endpoint(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        with TestClient(api.app) as client:
            r = client.get("/components")
            assert r.status_code == 200
            assert "chunker" in r.json()
    finally:
        api.app.dependency_overrides.clear()


def test_serve_original_file(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        with TestClient(api.app) as client:
            cid = client.post("/corpora", json={"name": "files"}).json()["id"]
            did = client.post(f"/corpora/{cid}/documents",
                              files={"file": ("a.txt", b"hello bytes", "text/plain")}).json()["id"]
            r = client.get(f"/documents/{did}/file")
            assert r.status_code == 200
            assert r.content == b"hello bytes"
            assert client.get("/documents/99999/file").status_code == 404
    finally:
        api.app.dependency_overrides.clear()


def test_list_virtual_models(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        with TestClient(api.app) as client:
            cid = client.post("/corpora", json={"name": "vm"}).json()["id"]
            client.post("/virtual-models",
                        json={"name": "ask-vm", "corpus_id": cid, "provider": "openai", "model": "gpt-x"})
            r = client.get("/virtual-models")
            assert r.status_code == 200
            assert [m["name"] for m in r.json()] == ["ask-vm"]
    finally:
        api.app.dependency_overrides.clear()
