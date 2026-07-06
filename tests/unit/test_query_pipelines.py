import pytest
from fastapi.testclient import TestClient

from madosho_server import db, membership, query_api


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'q.db'}")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))


def _seed():
    with db.SessionLocal() as s:
        c = db.Corpus(name="aero", config={"corpus": "aero", "query": []})
        s.add(c); s.commit(); s.refresh(c)
        d = db.Document(filename="contract.pdf", content_hash="h",
                        file_uri="u", mimetype="application/pdf", status="indexed")
        s.add(d); s.commit(); s.refresh(d)
        membership.add_membership(s, d.id, c.id); s.commit()
        for name, score, slots in (
            ("contract_docling", 8.0, {"extract": "docling", "chunk": "docling-hybrid",
                                       "index": "granite"}),
            ("contract_fast", 6.0, {"extract": "pypdfium", "chunk": "fixed", "index": "nomic"})):
            p = db.Pipeline(document_id=d.id, name=name, config={},
                            slots=slots, collection=f"m_{name}", status="indexed")
            s.add(p); s.commit()
            s.add(db.TechniqueRating(corpus_id=c.id, document_id=d.id, dimension="embed",
                                     candidate_config=name, score=score, source="static"))
            s.commit()
        return c.id


def test_list_pipelines_shape_and_effective_flag(env):
    with TestClient(query_api.app) as client:
        _seed()
        r = client.get("/corpora/aero/pipelines")
        assert r.status_code == 200
        rows = {p["name"]: p for p in r.json()}
        assert set(rows) == {"contract_docling", "contract_fast"}
        assert rows["contract_docling"]["rating"] == 8.0
        assert rows["contract_docling"]["slots"]["extract"] == "docling"
        assert rows["contract_docling"]["status"] == "indexed"
        assert rows["contract_docling"]["effective"] is True    # highest-rated
        assert rows["contract_fast"]["effective"] is False


def test_list_pipelines_unknown_corpus_404(env):
    with TestClient(query_api.app) as client:
        assert client.get("/corpora/ghost/pipelines").status_code == 404
