"""DELETE /documents/{id}/pipelines/{pid} -- remove a single pipeline. Drops the
row + defers its collection; leaves document-scoped ratings/comparisons alone and
keeps the shared file blob (the surviving document protects it)."""
from fastapi.testclient import TestClient

from madosho_server import api, db


def _client(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'pipedel.db'}")
    db.create_all()
    # capture deferred cleanup jobs instead of touching procrastinate
    deferred: list[tuple] = []
    api.app.dependency_overrides[api.get_enqueue_delete] = lambda: (
        lambda session, collections, file_uri: deferred.append((list(collections), file_uri)))
    return TestClient(api.app), deferred


def _doc(session, filename="f35.pdf"):
    d = db.Document(filename=filename, content_hash=filename, file_uri=f"blob/{filename}",
                    mimetype="application/pdf", status="indexed")
    session.add(d)
    session.flush()
    return d


def _pipe(session, doc_id, name, *, is_default=False, collection="col", status="indexed"):
    p = db.Pipeline(document_id=doc_id, name=name, is_default=is_default,
                    collection=collection, status=status)
    session.add(p)
    session.flush()
    return p


def test_delete_pipeline_removes_row_and_defers_collection_drop(tmp_path):
    client, deferred = _client(tmp_path)
    try:
        with db.SessionLocal() as s:
            doc = _doc(s)
            _pipe(s, doc.id, "default", is_default=True, collection="col_default")
            extra = _pipe(s, doc.id, "vision", collection="col_vision")
            s.commit()
            doc_id, extra_id = doc.id, extra.id
        r = client.delete(f"/documents/{doc_id}/pipelines/{extra_id}")
        assert r.status_code == 204
        with db.SessionLocal() as s:
            assert s.get(db.Pipeline, extra_id) is None              # gone
            assert s.query(db.Pipeline).count() == 1                 # default survives
            assert s.get(db.Document, doc_id) is not None            # document untouched
        # exactly the deleted pipeline's collection deferred; blob kept (doc's file_uri passed)
        assert deferred == [(["col_vision"], "blob/f35.pdf")]
    finally:
        api.app.dependency_overrides.clear()


def test_delete_pipeline_leaves_document_ratings_untouched(tmp_path):
    client, _ = _client(tmp_path)
    try:
        with db.SessionLocal() as s:
            doc = _doc(s)
            p = _pipe(s, doc.id, "vision", collection="col_vision")
            s.add(db.TechniqueRating(document_id=doc.id, dimension="extraction",
                                     candidate_config="vision", score=4.0, source="static"))
            s.commit()
            doc_id, pid = doc.id, p.id
        assert client.delete(f"/documents/{doc_id}/pipelines/{pid}").status_code == 204
        with db.SessionLocal() as s:
            # the technique rating is document knowledge, not pipeline state -> kept
            assert s.query(db.TechniqueRating).count() == 1
    finally:
        api.app.dependency_overrides.clear()


def test_delete_selected_pipeline_clears_the_selection(tmp_path):
    client, _ = _client(tmp_path)
    try:
        with db.SessionLocal() as s:
            doc = _doc(s)
            p = _pipe(s, doc.id, "vision", collection="col_vision")
            s.flush()
            doc.selected_pipeline_id = p.id
            s.commit()
            doc_id, pid = doc.id, p.id
        assert client.delete(f"/documents/{doc_id}/pipelines/{pid}").status_code == 204
        with db.SessionLocal() as s:
            assert s.get(db.Document, doc_id).selected_pipeline_id is None
    finally:
        api.app.dependency_overrides.clear()


def test_delete_pipeline_wrong_document_is_404(tmp_path):
    client, _ = _client(tmp_path)
    try:
        with db.SessionLocal() as s:
            a, b = _doc(s, "a.pdf"), _doc(s, "b.pdf")
            p = _pipe(s, a.id, "vision")
            s.commit()
            b_id, pid = b.id, p.id
        # pipeline belongs to doc a, not b
        assert client.delete(f"/documents/{b_id}/pipelines/{pid}").status_code == 404
    finally:
        api.app.dependency_overrides.clear()


def test_delete_collectionless_pipeline_skips_deferred_cleanup(tmp_path):
    client, deferred = _client(tmp_path)
    try:
        with db.SessionLocal() as s:
            doc = _doc(s)
            p = _pipe(s, doc.id, "never_built", collection="", status="failed")
            s.commit()
            doc_id, pid = doc.id, p.id
        assert client.delete(f"/documents/{doc_id}/pipelines/{pid}").status_code == 204
        assert deferred == []                                        # nothing to drop, no job
    finally:
        api.app.dependency_overrides.clear()
