import io
import pytest
from fastapi.testclient import TestClient

from madosho_server import api, db, membership


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'a.db'}")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))


def _corpus_and_doc(client):
    c = client.post("/corpora", json={"name": "aero"}).json()
    files = {"file": ("contract.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")}
    d = client.post(f"/corpora/{c['id']}/documents", files=files).json()
    return c, d


def test_create_pipeline_enqueues_build(env, monkeypatch):
    enqueued = []
    monkeypatch.setattr(api, "transactional_enqueue", lambda s, did: None)  # skip ingest defer
    monkeypatch.setattr(api, "transactional_enqueue_build_pipeline",
                        lambda s, pid: enqueued.append(pid))
    with TestClient(api.app) as client:
        c, d = _corpus_and_doc(client)
        body = {"name": "contract_fast",
                "config": {"corpus": "aero",
                           "ingest": {"parser": "docling", "chunker": "docling-hybrid",
                                      "embedder": "granite-embedding-english-r2",
                                      "store": {"qdrant": {"url": "http://qdrant:6333"}},
                                      "indexes": ["bm25", "dense"]},
                           "query": ["keyword_search", "semantic_search", "fuse"]}}
        r = client.post(f"/documents/{d['id']}/pipelines", json=body)
        assert r.status_code == 202
        out = r.json()
        assert out["name"] == "contract_fast" and out["status"] == "building"
        assert out["collection"].startswith("madosho_p")
        assert out["slots"]["index"] == "granite-embedding-english-r2"
        with db.SessionLocal() as s:
            p = s.query(db.Pipeline).filter_by(name="contract_fast").one()
            assert p.config["ingest"]["store"]["qdrant"]["collection"] == p.collection
        assert enqueued == [out["id"]]


def test_create_pipeline_rejects_duplicate_name(env, monkeypatch):
    monkeypatch.setattr(api, "transactional_enqueue", lambda s, did: None)
    monkeypatch.setattr(api, "transactional_enqueue_build_pipeline", lambda s, pid: None)
    with TestClient(api.app) as client:
        c, d = _corpus_and_doc(client)
        body = {"name": "dup", "config": {"corpus": "aero",
                "ingest": {"parser": "docling", "chunker": "docling-hybrid",
                           "embedder": "granite-embedding-english-r2",
                           "store": {"qdrant": {"url": "http://qdrant:6333"}},
                           "indexes": ["bm25", "dense"]}, "query": ["keyword_search"]}}
        assert client.post(f"/documents/{d['id']}/pipelines", json=body).status_code == 202
        assert client.post(f"/documents/{d['id']}/pipelines", json=body).status_code == 409


def test_create_pipeline_rejects_invalid_config(env, monkeypatch):
    monkeypatch.setattr(api, "transactional_enqueue", lambda s, did: None)
    monkeypatch.setattr(api, "transactional_enqueue_build_pipeline", lambda s, pid: None)
    with TestClient(api.app) as client:
        c, d = _corpus_and_doc(client)
        body = {"name": "bad", "config": {"corpus": "aero"}}   # missing ingest/query
        assert client.post(f"/documents/{d['id']}/pipelines", json=body).status_code == 422


def test_create_pipeline_missing_document_404(env, monkeypatch):
    monkeypatch.setattr(api, "transactional_enqueue", lambda s, did: None)
    monkeypatch.setattr(api, "transactional_enqueue_build_pipeline", lambda s, pid: None)
    with TestClient(api.app) as client:
        body = {"name": "x", "config": {"corpus": "aero",
                "ingest": {"parser": "docling", "chunker": "docling-hybrid",
                           "embedder": "granite-embedding-english-r2",
                           "store": {"qdrant": {"url": "http://qdrant:6333"}},
                           "indexes": ["bm25", "dense"]}, "query": ["keyword_search"]}}
        assert client.post("/documents/99999/pipelines", json=body).status_code == 404


def test_delete_document_removes_pipelines_and_enqueues_collection_drop(env, monkeypatch):
    # H5: upload now creates a default pipeline, so deleting a document enqueues
    # its collection alongside any manually added pipelines' collections.
    monkeypatch.setattr(api, "transactional_enqueue", lambda s, did: None)
    calls = {}
    monkeypatch.setattr(api, "transactional_enqueue_delete",
                        lambda s, collections, uri: calls.update(
                            collections=collections, uri=uri))
    with TestClient(api.app) as client:
        c, d = _corpus_and_doc(client)
        with db.SessionLocal() as s:
            s.add(db.Pipeline(document_id=d["id"], name="p1",
                              config={}, collection="madosho_aero_10", status="indexed"))
            s.add(db.Pipeline(document_id=d["id"], name="p2",
                              config={}, collection="madosho_aero_11", status="indexed"))
            s.commit()
        assert client.delete(f"/documents/{d['id']}").status_code == 204
        with db.SessionLocal() as s:
            assert s.query(db.Pipeline).filter_by(document_id=d["id"]).count() == 0
        # Upload creates a default pipeline (H5); its madosho_p<N> collection is also
        # included in the drop. Assert the two explicit collections are in the set.
        assert {"madosho_aero_10", "madosho_aero_11"}.issubset(set(calls["collections"]))


def test_rebuild_document_resets_and_reenqueues(env, monkeypatch):
    enqueued = []
    # _corpus_and_doc's upload enqueues once; capture rebuild's re-enqueue too.
    monkeypatch.setattr(api, "transactional_enqueue", lambda s, did: enqueued.append(did))
    with TestClient(api.app) as client:
        _, d = _corpus_and_doc(client)
        with db.SessionLocal() as s:
            doc = s.get(db.Document, d["id"])
            doc.status, doc.error = "failed", "boom"
            s.commit()
        enqueued.clear()
        r = client.post(f"/documents/{d['id']}/rebuild")
        assert r.status_code == 202 and r.json()["status"] == "rebuilding"
        assert enqueued == [d["id"]]
        with db.SessionLocal() as s:
            doc = s.get(db.Document, d["id"])
            assert doc.status == "received" and doc.error is None


def test_rebuild_document_404_when_missing(env):
    with TestClient(api.app) as client:
        assert client.post("/documents/99999/rebuild").status_code == 404


def test_reconfigure_document_swaps_recipe_and_rebuilds(env, monkeypatch):
    enqueued = []
    monkeypatch.setattr(api, "transactional_enqueue", lambda s, did: enqueued.append(did))
    with TestClient(api.app) as client:
        _, d = _corpus_and_doc(client)        # upload makes a default pipeline (docling stack)
        enqueued.clear()
        r = client.post(f"/documents/{d['id']}/reconfigure", json={"chunker": "recursive-text"})
        assert r.status_code == 202 and r.json()["status"] == "rebuilding"
        assert enqueued == [d["id"]]           # re-enqueued the ingest
        with db.SessionLocal() as s:
            p = s.query(db.Pipeline).filter_by(document_id=d["id"], is_default=True).one()
            assert p.slots["chunk"] == "recursive-text"   # new recipe took effect
            assert p.status == "building"
            assert s.get(db.Document, d["id"]).status == "received"


def test_reconfigure_document_404_when_missing(env):
    with TestClient(api.app) as client:
        assert client.post("/documents/99999/reconfigure", json={"chunker": "recursive-text"}
                           ).status_code == 404


def test_list_document_pipelines_shape_and_effective(env, monkeypatch):
    # H5: upload now creates a default pipeline (contract_docling, building status).
    # We add a second pipeline (d_docling, indexed) and check its shape.
    # The indexed pipeline is effective; the building default is not.
    monkeypatch.setattr(api, "transactional_enqueue", lambda s, did: None)
    with TestClient(api.app) as client:
        c, d = _corpus_and_doc(client)
        with db.SessionLocal() as s:
            p = db.Pipeline(document_id=d["id"], name="d_docling",
                            config={}, collection="col", status="indexed", is_default=False,
                            slots={"extract": "docling", "chunk": "docling-hybrid", "index": "granite"})
            s.add(p)
            s.flush()
            s.add(db.TechniqueRating(corpus_id=c["id"], document_id=d["id"], dimension="extraction",
                                     candidate_config="d_docling", score=3.0, source="static"))
            s.add(db.TechniqueRating(corpus_id=c["id"], document_id=d["id"], dimension="chunk",
                                     candidate_config="d_docling", score=2.5, source="static"))
            s.commit()
        r = client.get(f"/documents/{d['id']}/pipelines")
        assert r.status_code == 200
        rows = r.json()
        # H5: two pipelines (default from upload + d_docling); find d_docling by name
        assert len(rows) == 2
        row = next(rw for rw in rows if rw["name"] == "d_docling")
        assert row["is_default"] is False
        assert row["slots"]["extract"] == "docling"
        assert row["steps"] == {"extract": 3.0, "chunk": 2.5}
        assert row["rating"] == 5.5
        assert row["status"] == "indexed"
        assert row["effective"] is True            # only indexed pipeline -> effective


def test_list_document_pipelines_404_when_no_document(env):
    with TestClient(api.app) as client:
        r = client.get("/documents/999/pipelines")
        assert r.status_code == 404


def test_list_document_pipelines_exposes_build_progress(env, monkeypatch):
    """The doc page polls this for the live build console, so progress must ride
    along on each row (defaulting to {} when nothing has been published).
    H5: upload creates a default pipeline too; find the target row by name."""
    monkeypatch.setattr(api, "transactional_enqueue", lambda s, did: None)
    with TestClient(api.app) as client:
        c, d = _corpus_and_doc(client)
        with db.SessionLocal() as s:
            s.add(db.Pipeline(document_id=d["id"], name="p_build",
                              config={}, collection="col", status="building",
                              progress={"phase": "extract", "log": [{"t": 1, "msg": "extract"}]}))
            s.commit()
        rows = client.get(f"/documents/{d['id']}/pipelines").json()
        row = next(rw for rw in rows if rw["name"] == "p_build")
        assert row["progress"]["phase"] == "extract"
        assert row["progress"]["log"][0]["msg"] == "extract"


def test_pipeline_artifacts_returns_its_own_chunks_and_tables(env, monkeypatch):
    monkeypatch.setattr(api, "transactional_enqueue", lambda s, did: None)
    with TestClient(api.app) as client:
        c, d = _corpus_and_doc(client)
        with db.SessionLocal() as s:
            p = db.Pipeline(document_id=d["id"], name="p_art",
                            config={}, collection="col", status="indexed",
                            artifacts={"chunks": [{"id": "x1", "text": "hello", "position": 0, "page": 2}],
                                       "blocks": [{"kind": "table", "content": "| a |",
                                                   "provenance": {"page": 3, "bbox": [1, 2, 3, 4]}}]})
            s.add(p); s.commit()
            pid = p.id
        r = client.get(f"/pipelines/{pid}/artifacts")
        assert r.status_code == 200
        body = r.json()
        assert body["document_id"] == d["id"]
        assert body["chunks"][0] == {"id": "x1", "text": "hello", "position": 0, "page": 2}
        assert body["tables"][0]["content"] == "| a |" and body["tables"][0]["page"] == 3


def test_pipeline_artifacts_404_and_409(env, monkeypatch):
    monkeypatch.setattr(api, "transactional_enqueue", lambda s, did: None)
    with TestClient(api.app) as client:
        c, d = _corpus_and_doc(client)
        assert client.get("/pipelines/999/artifacts").status_code == 404   # no pipeline
        with db.SessionLocal() as s:
            p = db.Pipeline(document_id=d["id"], name="p_none",
                            config={}, collection="col", status="building")  # still building -> no artifacts
            s.add(p); s.commit()
            pid = p.id
        assert client.get(f"/pipelines/{pid}/artifacts").status_code == 409


def test_set_selected_pipeline_sets_and_clears(env, monkeypatch):
    monkeypatch.setattr(api, "transactional_enqueue", lambda s, did: None)
    with TestClient(api.app) as client:
        c, d = _corpus_and_doc(client)
        with db.SessionLocal() as s:
            p = db.Pipeline(document_id=d["id"], name="d_alt",
                            config={}, collection="col", status="indexed")
            s.add(p)
            s.commit()
            pid = p.id
        # set
        r = client.put(f"/documents/{d['id']}/selected-pipeline", json={"pipeline_id": pid})
        assert r.status_code == 200 and r.json()["selected_pipeline_id"] == pid
        with db.SessionLocal() as s:
            assert s.get(db.Document, d["id"]).selected_pipeline_id == pid
        # clear
        r = client.put(f"/documents/{d['id']}/selected-pipeline", json={"pipeline_id": None})
        assert r.status_code == 200 and r.json()["selected_pipeline_id"] is None
        with db.SessionLocal() as s:
            assert s.get(db.Document, d["id"]).selected_pipeline_id is None


def test_set_selected_pipeline_rejects_foreign_pipeline(env, monkeypatch):
    monkeypatch.setattr(api, "transactional_enqueue", lambda s, did: None)
    with TestClient(api.app) as client:
        c, d = _corpus_and_doc(client)
        # create a real second document in the same corpus, then attach the pipeline to it
        with db.SessionLocal() as s:
            d2 = db.Document(filename="other.pdf",
                             content_hash="deadbeef00000002", file_uri="u2",
                             mimetype="application/pdf", status="indexed")
            s.add(d2)
            s.flush()
            p = db.Pipeline(document_id=d2.id, name="other",
                            config={}, collection="col2", status="indexed")
            s.add(p)
            s.commit()
            pid = p.id
        # pipeline genuinely belongs to d2, not d -> must be rejected
        r = client.put(f"/documents/{d['id']}/selected-pipeline", json={"pipeline_id": pid})
        assert r.status_code == 422


def test_get_document_exposes_selected_pipeline_id(env, monkeypatch):
    monkeypatch.setattr(api, "transactional_enqueue", lambda s, did: None)
    with TestClient(api.app) as client:
        c, d = _corpus_and_doc(client)
        r = client.get(f"/documents/{d['id']}")
        assert r.status_code == 200
        assert "selected_pipeline_id" in r.json()
        assert r.json()["selected_pipeline_id"] is None


def _indexed_pipeline(s, c, d, name, slots):
    p = db.Pipeline(document_id=d["id"], name=name, config={},
                    collection=name, status="indexed", slots=slots)
    s.add(p)


def test_recommended_pipeline_endpoint_returns_combo(env, monkeypatch):
    monkeypatch.setattr(api, "transactional_enqueue", lambda s, did: None)
    with TestClient(api.app) as client:
        c, d = _corpus_and_doc(client)
        with db.SessionLocal() as s:
            _indexed_pipeline(s, c, d, "p1", {"extract": "docling", "chunk": "hybrid", "index": "granite"})
            _indexed_pipeline(s, c, d, "p2", {"extract": "pypdfium2", "chunk": "late", "index": "nomic"})
            for name, dim, score in [("p1", "extraction", 4.0), ("p2", "extraction", 3.0),
                                     ("p1", "chunk", 2.0), ("p2", "chunk", 3.5),
                                     ("p1", "embed", 2.0), ("p2", "embed", 2.5)]:
                s.add(db.TechniqueRating(corpus_id=c["id"], document_id=d["id"], dimension=dim,
                                         candidate_config=name, score=score, source="static"))
            s.commit()
        r = client.get(f"/documents/{d['id']}/recommended-pipeline")
        assert r.status_code == 200
        body = r.json()
        assert body["slots"] == {"extract": "docling", "chunk": "late", "index": "nomic"}
        assert body["projected_rating"] == 10.0
        assert body["already_built"] is False


def test_recommended_pipeline_endpoint_null_when_nothing_to_suggest(env, monkeypatch):
    monkeypatch.setattr(api, "transactional_enqueue", lambda s, did: None)
    with TestClient(api.app) as client:
        c, d = _corpus_and_doc(client)
        r = client.get(f"/documents/{d['id']}/recommended-pipeline")
        assert r.status_code == 200
        assert r.json() is None


def test_recommended_pipeline_endpoint_404_when_no_document(env):
    with TestClient(api.app) as client:
        assert client.get("/documents/999/recommended-pipeline").status_code == 404


def test_cube_surfaces_per_pipeline_rows(env):
    """The per-pipeline split view surfaces one row per named pipeline, each
    carrying its own build-dim scores (candidate_config=name). This is the exact
    comparison the old per-document cube collapsed away."""
    with TestClient(api.app) as client:
        c = client.post("/corpora", json={"name": "aero"}).json()
        with db.SessionLocal() as s:
            d = db.Document(filename="a.pdf", content_hash="h",
                            file_uri="u", mimetype="application/pdf", status="indexed")
            s.add(d); s.commit(); s.refresh(d)
            membership.add_membership(s, d.id, c["id"])
            p1 = db.Pipeline(document_id=d.id, name="a_docling", status="indexed")
            p2 = db.Pipeline(document_id=d.id, name="a_docling_2", status="indexed")
            s.add(p1); s.add(p2); s.commit()
            # Each pipeline scores embed differently -> distinct rows, not a collapse.
            s.add(db.TechniqueRating(corpus_id=None, document_id=d.id, dimension="embed",
                                     candidate_config="a_docling", score=4.0, source="static"))
            s.add(db.TechniqueRating(corpus_id=None, document_id=d.id, dimension="embed",
                                     candidate_config="a_docling_2", score=2.0, source="static"))
            s.commit()
        cube = client.get(f"/corpora/{c['id']}/ratings").json()
        pipes = {p["name"]: p for p in cube["documents"][0]["pipelines"]}
        assert pipes["a_docling"]["cells"]["embed"]["score"] == 4.0
        assert pipes["a_docling_2"]["cells"]["embed"]["score"] == 2.0


def test_create_pipeline_from_recipe_only(env, monkeypatch):
    enqueued = []
    monkeypatch.setattr(api, "transactional_enqueue", lambda s, did: None)
    monkeypatch.setattr(api, "transactional_enqueue_build_pipeline",
                        lambda s, pid: enqueued.append(pid))
    with TestClient(api.app) as client:
        c, d = _corpus_and_doc(client)
        # No `config` key at all — only a recipe. The server must synthesize a
        # valid kernel config from the library default base + this parser.
        # recursive-text pairs with any parser (docling-hybrid would not).
        body = {"name": "alt_fast", "parser": "pypdfium2", "chunker": "recursive-text"}
        r = client.post(f"/documents/{d['id']}/pipelines", json=body)
        assert r.status_code == 202, r.text
        out = r.json()
        assert out["name"] == "alt_fast" and out["status"] == "building"
        assert out["slots"]["extract"] == "pypdfium2"   # recipe overlay took effect
        assert enqueued == [out["id"]]
