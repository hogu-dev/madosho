import io
from fastapi.testclient import TestClient
from sqlalchemy import select

from madosho_server import api, db, membership


def _client(tmp_path, monkeypatch, enqueued):
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "co"))
    db.configure_engine(f"sqlite:///{tmp_path/'a.db'}")
    db.create_all()
    # capture deferred ingest jobs instead of touching procrastinate
    api.app.dependency_overrides[api.get_enqueue] = lambda: (
        lambda session, document_id: enqueued.append(document_id))
    return TestClient(api.app)


def _upload(client, corpus_id, name="contract.pdf", body=b"%PDF-1.4 hello"):
    files = {"file": (name, io.BytesIO(body), "application/pdf")}
    return client.post(f"/corpora/{corpus_id}/documents", files=files)


def test_same_file_two_corpora_is_one_document_indexed_once(tmp_path, monkeypatch):
    enqueued: list[int] = []
    client = _client(tmp_path, monkeypatch, enqueued)
    try:
        a = client.post("/corpora", json={"name": "alpha"}).json()["id"]
        b = client.post("/corpora", json={"name": "beta"}).json()["id"]
        r1 = _upload(client, a)
        assert r1.status_code == 202
        doc_id = r1.json()["id"]
        r2 = _upload(client, b)                      # same bytes, different corpus
        assert r2.status_code in (200, 202)
        assert r2.json()["id"] == doc_id            # ONE document row
        with db.SessionLocal() as s:
            assert s.query(db.Document).count() == 1
            assert s.query(db.DocumentCorpus).count() == 2   # member of both
        assert enqueued == [doc_id]                 # indexed once, not twice
    finally:
        api.app.dependency_overrides.clear()


def test_reupload_same_corpus_is_idempotent(tmp_path, monkeypatch):
    enqueued: list[int] = []
    client = _client(tmp_path, monkeypatch, enqueued)
    try:
        a = client.post("/corpora", json={"name": "alpha"}).json()["id"]
        first = _upload(client, a).json()["id"]
        again = _upload(client, a)
        assert again.json()["id"] == first
        with db.SessionLocal() as s:
            assert s.query(db.DocumentCorpus).count() == 1   # still one membership
        assert enqueued == [first]
    finally:
        api.app.dependency_overrides.clear()


def test_upload_creates_default_pipeline_before_ingest(tmp_path, monkeypatch):
    enqueued: list[int] = []
    client = _client(tmp_path, monkeypatch, enqueued)
    try:
        a = client.post("/corpora", json={"name": "alpha"}).json()["id"]
        doc_id = _upload(client, a).json()["id"]
        with db.SessionLocal() as s:
            ps = s.query(db.Pipeline).filter_by(document_id=doc_id).all()
            assert len(ps) == 1 and ps[0].is_default
            assert ps[0].collection == f"madosho_p{ps[0].id}"
        assert enqueued == [doc_id]
    finally:
        api.app.dependency_overrides.clear()


def test_second_corpus_membership_adds_no_pipeline(tmp_path, monkeypatch):
    enqueued: list[int] = []
    client = _client(tmp_path, monkeypatch, enqueued)
    try:
        a = client.post("/corpora", json={"name": "alpha"}).json()["id"]
        b = client.post("/corpora", json={"name": "beta"}).json()["id"]
        doc_id = _upload(client, a).json()["id"]
        _upload(client, b)                       # membership only
        with db.SessionLocal() as s:
            assert s.query(db.Pipeline).filter_by(document_id=doc_id).count() == 1
        assert enqueued == [doc_id]              # still indexed once
    finally:
        api.app.dependency_overrides.clear()


def test_get_documents_lists_library_with_corpora_chips(tmp_path, monkeypatch):
    enqueued: list[int] = []
    client = _client(tmp_path, monkeypatch, enqueued)
    try:
        a = client.post("/corpora", json={"name": "alpha"}).json()["id"]
        b = client.post("/corpora", json={"name": "beta"}).json()["id"]
        doc_id = _upload(client, a).json()["id"]
        _upload(client, b)                       # same file -> membership of both
        lib = client.get("/documents")
        assert lib.status_code == 200
        rows = lib.json()
        assert len(rows) == 1                    # ONE document in the library
        row = rows[0]
        assert row["id"] == doc_id
        assert row["filename"] == "contract.pdf"
        assert {c["name"] for c in row["corpora"]} == {"alpha", "beta"}
        assert "rating" in row                   # present (None pre-index in unit tests)
    finally:
        api.app.dependency_overrides.clear()


def test_get_document_includes_in_corpora_list(tmp_path, monkeypatch):
    enqueued: list[int] = []
    client = _client(tmp_path, monkeypatch, enqueued)
    try:
        a = client.post("/corpora", json={"name": "alpha"}).json()["id"]
        doc_id = _upload(client, a).json()["id"]
        r = client.get(f"/documents/{doc_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == doc_id
        assert [c["name"] for c in body["corpora"]] == ["alpha"]
    finally:
        api.app.dependency_overrides.clear()


def test_get_document_404_for_missing(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, [])
    try:
        assert client.get("/documents/9999").status_code == 404
    finally:
        api.app.dependency_overrides.clear()


def test_add_existing_document_to_corpus_is_membership_only(tmp_path, monkeypatch):
    enqueued: list[int] = []
    client = _client(tmp_path, monkeypatch, enqueued)
    try:
        a = client.post("/corpora", json={"name": "alpha"}).json()["id"]
        b = client.post("/corpora", json={"name": "beta"}).json()["id"]
        doc_id = _upload(client, a).json()["id"]
        assert enqueued == [doc_id]              # indexed once at upload
        r = client.post(f"/corpora/{b}/documents/{doc_id}")
        assert r.status_code == 200
        assert r.json()["id"] == doc_id
        # idempotent: adding again does not duplicate the join row
        client.post(f"/corpora/{b}/documents/{doc_id}")
        with db.SessionLocal() as s:
            assert s.query(db.DocumentCorpus).count() == 2   # alpha + beta, once each
        assert enqueued == [doc_id]              # NEVER re-indexed
    finally:
        api.app.dependency_overrides.clear()


def test_add_document_to_corpus_404s(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, [])
    try:
        a = client.post("/corpora", json={"name": "alpha"}).json()["id"]
        doc_id = _upload(client, a).json()["id"]
        assert client.post(f"/corpora/9999/documents/{doc_id}").status_code == 404
        assert client.post(f"/corpora/{a}/documents/9999").status_code == 404
    finally:
        api.app.dependency_overrides.clear()


def test_remove_membership_keeps_document(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, [])
    try:
        a = client.post("/corpora", json={"name": "alpha"}).json()["id"]
        doc_id = _upload(client, a).json()["id"]
        r = client.delete(f"/corpora/{a}/documents/{doc_id}")
        assert r.status_code == 204
        with db.SessionLocal() as s:
            assert s.query(db.DocumentCorpus).count() == 0   # membership gone
            assert s.query(db.Document).count() == 1         # document stays
        # idempotent
        assert client.delete(f"/corpora/{a}/documents/{doc_id}").status_code == 204
        # corpus 404 still distinguished
        assert client.delete(f"/corpora/9999/documents/{doc_id}").status_code == 404
    finally:
        api.app.dependency_overrides.clear()


def _client2(tmp_path, monkeypatch, ingested, built):
    """Like _client but also captures per-pipeline build enqueues (Task 5/6)."""
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "co"))
    db.configure_engine(f"sqlite:///{tmp_path/'a2.db'}")
    db.create_all()
    api.app.dependency_overrides[api.get_enqueue] = lambda: (
        lambda session, document_id: ingested.append(document_id))
    api.app.dependency_overrides[api.get_enqueue_build_pipeline] = lambda: (
        lambda session, pipeline_id: built.append(pipeline_id))
    return TestClient(api.app)


def _lib_upload(client, filename="contract.pdf", body=b"%PDF-1.4 hello", **recipe):
    files = {"file": (filename, io.BytesIO(body), "application/pdf")}
    return client.post("/documents", files=files, data=recipe)


def test_library_upload_new_doc_builds_default_pipeline(tmp_path, monkeypatch):
    ingested: list[int] = []; built: list[int] = []
    client = _client2(tmp_path, monkeypatch, ingested, built)
    try:
        r = _lib_upload(client, parser="pypdfium2", chunker="recursive-text")
        assert r.status_code == 202
        doc_id = r.json()["id"]
        with db.SessionLocal() as s:
            ps = s.query(db.Pipeline).filter_by(document_id=doc_id).all()
            assert len(ps) == 1 and ps[0].is_default
            assert ps[0].slots["extract"] == "pypdfium2"          # recipe applied
            assert ps[0].collection == f"madosho_p{ps[0].id}"
            assert s.query(db.DocumentCorpus).count() == 0        # library doc, no membership
        assert ingested == [doc_id] and built == []              # ingest builds the default
    finally:
        api.app.dependency_overrides.clear()


def test_library_upload_existing_doc_new_name_builds_extra_pipeline(tmp_path, monkeypatch):
    ingested: list[int] = []; built: list[int] = []
    client = _client2(tmp_path, monkeypatch, ingested, built)
    try:
        doc_id = _lib_upload(client).json()["id"]                # default <stem>_docling
        r = _lib_upload(client, parser="pypdfium2", chunker="recursive-text", name="contract_alt")
        assert r.status_code == 202 and r.json()["id"] == doc_id  # SAME document
        with db.SessionLocal() as s:
            names = {p.name for p in s.query(db.Pipeline).filter_by(document_id=doc_id)}
            assert names == {"contract_docling", "contract_alt"}
            alt = s.query(db.Pipeline).filter_by(name="contract_alt").one()
        assert ingested == [doc_id]                              # NOT re-ingested
        assert built == [alt.id]                                 # the extra pipeline is built
    finally:
        api.app.dependency_overrides.clear()


def test_library_upload_existing_doc_same_name_is_noop(tmp_path, monkeypatch):
    ingested: list[int] = []; built: list[int] = []
    client = _client2(tmp_path, monkeypatch, ingested, built)
    try:
        doc_id = _lib_upload(client).json()["id"]
        r = _lib_upload(client)                                  # same bytes, default name
        assert r.json()["id"] == doc_id
        with db.SessionLocal() as s:
            assert s.query(db.Pipeline).filter_by(document_id=doc_id).count() == 1
        assert ingested == [doc_id] and built == []             # nothing new built
    finally:
        api.app.dependency_overrides.clear()


def _upload_recipe(client, corpus_id, filename="contract.pdf",
                   body=b"%PDF-1.4 hello", **recipe):
    files = {"file": (filename, io.BytesIO(body), "application/pdf")}
    return client.post(f"/corpora/{corpus_id}/documents", files=files, data=recipe)


def test_upload_in_corpus_applies_recipe(tmp_path, monkeypatch):
    ingested: list[int] = []; built: list[int] = []
    client = _client2(tmp_path, monkeypatch, ingested, built)
    try:
        a = client.post("/corpora", json={"name": "alpha"}).json()["id"]
        r = _upload_recipe(client, a, parser="pypdfium2", chunker="recursive-text")
        assert r.status_code == 202
        doc_id = r.json()["id"]
        with db.SessionLocal() as s:
            p = s.query(db.Pipeline).filter_by(document_id=doc_id).one()
            assert p.is_default and p.slots["extract"] == "pypdfium2"
            assert s.query(db.DocumentCorpus).count() == 1   # membership written
        assert ingested == [doc_id]
    finally:
        api.app.dependency_overrides.clear()


def test_upload_in_corpus_without_recipe_unchanged(tmp_path, monkeypatch):
    ingested: list[int] = []; built: list[int] = []
    client = _client2(tmp_path, monkeypatch, ingested, built)
    try:
        a = client.post("/corpora", json={"name": "alpha"}).json()["id"]
        doc_id = _upload_recipe(client, a).json()["id"]        # no recipe fields
        with db.SessionLocal() as s:
            p = s.query(db.Pipeline).filter_by(document_id=doc_id).one()
            assert p.slots["extract"] == "docling"             # corpus default
        assert ingested == [doc_id]
    finally:
        api.app.dependency_overrides.clear()


def test_scoreboard_reads_doc_ratings_via_membership_join(tmp_path, monkeypatch):
    """H8: GET /corpora/{id}/ratings must surface doc-scoped rows (corpus_id=None) for
    member documents via the membership join. Per-pipeline build rows now key by
    candidate_config=pipeline name, so this checks the join still reaches them once
    the document carries a pipeline."""
    enqueued: list[int] = []
    client = _client(tmp_path, monkeypatch, enqueued)
    try:
        cid = client.post("/corpora", json={"name": "alpha"}).json()["id"]
        doc_id = _upload(client, cid).json()["id"]

        with db.SessionLocal() as s:
            # Upload already created the default pipeline (contract.pdf ->
            # contract_docling). Rate that pipeline's chunk step, doc-scoped,
            # corpus_id=None (what rate_pipeline_steps writes); the old
            # corpus_id==corpus_id filter would drop these silently.
            pname = s.scalars(select(db.Pipeline.name)
                              .where(db.Pipeline.document_id == doc_id)).first()
            s.add(db.TechniqueRating(
                corpus_id=None, document_id=doc_id,
                dimension="chunk", score=4.0, source="static",
                candidate_config=pname))
            s.commit()

        r = client.get(f"/corpora/{cid}/ratings")
        assert r.status_code == 200
        body = r.json()
        # The member document's group must appear (join reached the doc-scoped rows).
        doc_ids_in_cube = [d["document_id"] for d in body["documents"]]
        assert doc_id in doc_ids_in_cube, f"document {doc_id} missing from cube documents"
        group = next(d for d in body["documents"] if d["document_id"] == doc_id)
        assert group["pipelines"][0]["cells"]["chunk"]["score"] == 4.0
    finally:
        api.app.dependency_overrides.clear()


def _raising_enqueue(*_a, **_k):
    """An enqueue dep that fails with a NON-content_hash IntegrityError, simulating
    the cold-start flake where a different constraint (pipeline/procrastinate insert)
    fires inside the upload transaction. Leaves no competing Document row."""
    from sqlalchemy.exc import IntegrityError
    raise IntegrityError("INSERT", {}, Exception("simulated non-race constraint"))


def test_library_upload_non_race_integrity_error_is_truthful_500(tmp_path, monkeypatch):
    """The guard must claim 'upload race' ONLY for a genuine content_hash race (the
    re-select finds the winner). When a different constraint fires, no competing row
    exists, so it must surface truthfully as a 500 - not a misleading retryable 409.
    Pins the cold-start-flake fix on the library path (POST /documents)."""
    client = _client(tmp_path, monkeypatch, [])
    api.app.dependency_overrides[api.get_enqueue] = lambda: _raising_enqueue
    try:
        files = {"file": ("contract.pdf", io.BytesIO(b"%PDF-1.4 hello"), "application/pdf")}
        r = client.post("/documents", files=files)
        assert r.status_code == 500
        assert "race" not in r.json()["detail"].lower()     # not mislabeled as retryable
        with db.SessionLocal() as s:
            assert s.query(db.Document).count() == 0         # transaction rolled back cleanly
    finally:
        api.app.dependency_overrides.clear()


def test_corpus_upload_non_race_integrity_error_is_truthful_500(tmp_path, monkeypatch):
    """Same truthful-500 contract on the upload-in-corpus path (POST /corpora/{id}/documents)."""
    client = _client(tmp_path, monkeypatch, [])
    api.app.dependency_overrides[api.get_enqueue] = lambda: _raising_enqueue
    try:
        cid = client.post("/corpora", json={"name": "alpha"}).json()["id"]
        r = _upload(client, cid)
        assert r.status_code == 500
        assert "race" not in r.json()["detail"].lower()
        with db.SessionLocal() as s:
            assert s.query(db.Document).count() == 0
    finally:
        api.app.dependency_overrides.clear()


def test_scoreboard_excludes_non_member_doc_ratings(tmp_path, monkeypatch):
    """GET /corpora/{id}/ratings reads ONLY this corpus's member
    documents through the document_corpus join. A doc that is a member of a DIFFERENT
    corpus must not leak its ratings into this scoreboard. Pins the join scope so a
    future edit can't silently widen it back to every document."""
    enqueued: list[int] = []
    client = _client(tmp_path, monkeypatch, enqueued)
    try:
        a = client.post("/corpora", json={"name": "alpha"}).json()["id"]
        b = client.post("/corpora", json={"name": "beta"}).json()["id"]
        mine = _upload(client, a, name="mine.pdf", body=b"%PDF-1.4 mine").json()["id"]
        other = _upload(client, b, name="other.pdf", body=b"%PDF-1.4 other").json()["id"]
        with db.SessionLocal() as s:
            for doc_id in (mine, other):           # doc-scoped rating for each (corpus_id=None)
                s.add(db.TechniqueRating(
                    corpus_id=None, document_id=doc_id,
                    dimension="chunk", score=4.0, source="static", candidate_config=None))
            s.commit()

        body = client.get(f"/corpora/{a}/ratings").json()
        doc_ids = [d["document_id"] for d in body["documents"]]
        assert mine in doc_ids                     # member of alpha -> shown
        assert other not in doc_ids                # member of beta only -> excluded
    finally:
        api.app.dependency_overrides.clear()


def test_upload_rejects_incompatible_recipe_with_422(tmp_path, monkeypatch):
    # pymupdf parser + docling-hybrid chunker can never run -> reject up front,
    # no document row, no enqueued build (the frontend also blocks this, but the
    # API is the backstop for a hand-rolled call).
    enqueued: list[int] = []
    client = _client(tmp_path, monkeypatch, enqueued)
    try:
        a = client.post("/corpora", json={"name": "alpha"}).json()["id"]
        files = {"file": ("c.pdf", io.BytesIO(b"%PDF-1.4 hi"), "application/pdf")}
        r = client.post(f"/corpora/{a}/documents", files=files,
                        data={"parser": "pymupdf", "chunker": "docling-hybrid"})
        assert r.status_code == 422
        assert "docling-hybrid" in r.text or "incompatible" in r.text
        assert enqueued == []
        with db.SessionLocal() as s:
            assert s.query(db.Document).count() == 0

        # library upload path enforces the same rule
        r2 = client.post("/documents", files=files,
                         data={"parser": "pymupdf", "chunker": "docling-hybrid"})
        assert r2.status_code == 422
        assert enqueued == []
    finally:
        api.app.dependency_overrides.clear()
