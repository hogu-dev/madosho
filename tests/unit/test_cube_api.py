# tests/unit/test_cube_api.py
from fastapi.testclient import TestClient
from madosho_server import db, membership
from madosho_server.api import app, get_settings
from madosho_server.settings import Settings


def _client(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'api.db'}"); db.create_all()
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="sqlite://", qdrant_url="", filestore_dir=str(tmp_path),
        corpora_dir=str(tmp_path))
    app.dependency_overrides[db.get_session] = _session
    return TestClient(app)


def _session():
    s = db.SessionLocal()
    try: yield s
    finally: s.close()


def _build_ratings(s, doc_id, name, extraction, chunk, embed):
    for dim, score in (("extraction", extraction), ("chunk", chunk), ("embed", embed)):
        s.add(db.TechniqueRating(corpus_id=None, document_id=doc_id, dimension=dim,
                                 candidate_config=name, score=score, source="static",
                                 rater_version="static-v1"))


def test_cube_endpoint_groups_by_pipeline(tmp_path):
    client = _client(tmp_path)
    with db.SessionLocal() as s:
        c = db.Corpus(name="c", config={"corpus": "c"}); s.add(c); s.commit(); s.refresh(c)
        doc = db.Document(filename="f.pdf", content_hash="h",
                          file_uri="u", mimetype="application/pdf"); s.add(doc); s.commit(); s.refresh(doc)
        membership.add_membership(s, doc.id, c.id)
        # Two indexed pipelines on the document, each with its own build ratings.
        p1 = db.Pipeline(document_id=doc.id, name="f_docling", status="indexed")
        p2 = db.Pipeline(document_id=doc.id, name="f_docling_2", status="indexed")
        s.add(p1); s.add(p2); s.commit(); s.refresh(p1); s.refresh(p2)
        _build_ratings(s, doc.id, "f_docling", 4.5, 4, 4)
        _build_ratings(s, doc.id, "f_docling_2", 3.5, 3, 4)
        # Corpus-level retrieval strip (shared across the document's pipelines).
        for dim, score in (("keyword", 3.5), ("semantic", 3.8), ("rerank", 3.5)):
            s.add(db.TechniqueRating(corpus_id=c.id, document_id=None, dimension=dim,
                                     score=score, source="static", rater_version="static-v1"))
        s.commit()
        cid, p1_id = c.id, p1.id

    r = client.get(f"/corpora/{cid}/ratings")
    assert r.status_code == 200
    body = r.json()
    assert "rollup" not in body                       # per-document rollup is gone
    groups = body["documents"]
    assert len(groups) == 1
    g = groups[0]
    # retrieval strip is per-document, carries the corpus-level cells
    assert g["retrieval"]["semantic"]["score"] == 3.8
    # one row per pipeline (the thing the old exclusion filter suppressed), in id order
    names = [p["name"] for p in g["pipelines"]]
    assert names == ["f_docling", "f_docling_2"]
    p1_row = g["pipelines"][0]
    assert p1_row["pipeline_id"] == p1_id
    assert p1_row["cells"]["extraction"]["score"] == 4.5
    assert p1_row["build_total"] > 0
    # effective pipeline flagged (highest-rated indexed -> f_docling)
    assert {p["name"]: p["effective"] for p in g["pipelines"]} == \
        {"f_docling": True, "f_docling_2": False}
    app.dependency_overrides.clear()


def test_cube_endpoint_empty_when_no_pipelines(tmp_path):
    client = _client(tmp_path)
    with db.SessionLocal() as s:
        c = db.Corpus(name="c0", config={"corpus": "c0"}); s.add(c); s.commit(); s.refresh(c)
        doc = db.Document(filename="g.pdf", content_hash="h2",
                          file_uri="u2", mimetype="application/pdf"); s.add(doc); s.commit(); s.refresh(doc)
        membership.add_membership(s, doc.id, c.id); s.commit()
        cid = c.id
    body = client.get(f"/corpora/{cid}/ratings").json()
    assert body["documents"] == []                    # no pipelines -> no groups
    app.dependency_overrides.clear()


def test_get_and_put_ratings_config(tmp_path):
    client = _client(tmp_path)
    with db.SessionLocal() as s:
        c = db.Corpus(name="c2", config={"corpus": "c2"}); s.add(c); s.commit(); s.refresh(c)
        cid = c.id
    assert client.get(f"/corpora/{cid}/ratings/config").json()["trigger"] == "on-demand"
    r = client.put(f"/corpora/{cid}/ratings/config", json={"trigger": "on-ingest"})
    assert r.status_code == 200 and r.json()["trigger"] == "on-ingest"
    app.dependency_overrides.clear()
