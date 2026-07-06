# tests/unit/test_comparison_api.py
from fastapi.testclient import TestClient
from madosho_server import db, membership
from madosho_server.api import app, get_settings, get_enqueue_comparison
from madosho_server.settings import Settings


def _client(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'c.db'}"); db.create_all()
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="sqlite://", qdrant_url="", filestore_dir=str(tmp_path), corpora_dir=str(tmp_path))
    def _session():
        s = db.SessionLocal()
        try: yield s
        finally: s.close()
    app.dependency_overrides[db.get_session] = _session
    return TestClient(app)


def _seed(tmp_path):
    with db.SessionLocal() as s:
        c = db.Corpus(name="c", config={"corpus": "c"}); s.add(c); s.commit(); s.refresh(c)
        doc = db.Document(filename="f.pdf", content_hash="h", file_uri="u",
                          mimetype="application/pdf"); s.add(doc)
        doc.status = "indexed"
        s.commit(); s.refresh(doc)
        membership.add_membership(s, doc.id, c.id); s.commit()
        return c.id, doc.id


def test_run_enqueues_per_document(tmp_path):
    client = _client(tmp_path)
    cid, did = _seed(tmp_path)
    # add a non-indexed doc in the same corpus — must NOT be enqueued
    with db.SessionLocal() as s:
        other = db.Document(filename="g.pdf", content_hash="h2", file_uri="u2",
                            mimetype="application/pdf")
        s.add(other); s.commit()
    calls = []
    app.dependency_overrides[get_enqueue_comparison] = lambda: (lambda session, document_id: calls.append(document_id))
    r = client.post(f"/corpora/{cid}/ratings/run")
    assert r.status_code == 202 and r.json()["running"] == 1 and calls == [did]
    app.dependency_overrides.clear()


def test_comparison_returns_texts_and_diff_spans(tmp_path):
    client = _client(tmp_path)
    cid, did = _seed(tmp_path)
    with db.SessionLocal() as s:
        s.add(db.ExtractionComparison(document_id=did, engine_a="docling", text_a="the quick fox",
                                      engine_b="gemma-12b-vision", text_b="the slow fox",
                                      judge_model="gemma-e4b", judge_verdict="b", judge_score=4.0))
        s.commit()
    r = client.get(f"/documents/{did}/comparison")
    assert r.status_code == 200
    body = r.json()
    assert body["text_a"] == "the quick fox" and body["verdict"] == "b"
    assert body["diff"]["a"] and body["diff"]["b"]      # disagreement spans present
    app.dependency_overrides.clear()


def test_post_human_verdict_writes_human_rating(tmp_path):
    client = _client(tmp_path)
    cid, did = _seed(tmp_path)
    with db.SessionLocal() as s:
        s.add(db.ExtractionComparison(document_id=did, engine_a="docling", text_a="a",
                                      engine_b="gemma-12b-vision", text_b="b",
                                      judge_model="gemma-e4b", judge_verdict="b", judge_score=4.0))
        s.commit()
    r = client.post(f"/documents/{did}/comparison/verdict", json={"verdict": "a"})
    assert r.status_code == 200
    with db.SessionLocal() as s:
        comp = s.query(db.ExtractionComparison).filter_by(document_id=did).one()
        assert comp.human_verdict == "a"
        human = s.query(db.TechniqueRating).filter_by(document_id=did, source="human").one()
        assert human.dimension == "extraction"
    app.dependency_overrides.clear()
