from fastapi.testclient import TestClient

from madosho.core.types import Chunk, Hit
from madosho_server import db, membership, query_api


def _client(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'q.db'}"); db.create_all()
    return TestClient(query_api.app)


def _corpus(s, name="c"):
    c = db.Corpus(name=name, config={"corpus": name, "query": []})
    s.add(c); s.commit(); s.refresh(c); return c


def _indexed_doc(s, c, name="solo.pdf"):
    d = db.Document(filename=name, content_hash=name, file_uri="u",
                    mimetype="application/pdf", status="indexed")
    s.add(d); s.commit(); s.refresh(d)
    membership.add_membership(s, d.id, c.id); s.commit()
    p = db.Pipeline(document_id=d.id, name="solo_docling", config={}, status="indexed")
    s.add(p); s.commit()
    s.add(db.TechniqueRating(document_id=d.id, dimension="embed",
                             candidate_config="solo_docling", score=5.0, source="static"))
    s.commit()
    return d


class _FakeCorpus:
    def query(self, text):
        return [Hit(chunk_id="h1", score=1.0, source_index="rrf",
                    chunk=Chunk(id="h1", doc_id="kd", text="t", page=1,
                                position=0, metadata={"source": "/x.pdf"}))]


def test_query_requires_exactly_one_target(tmp_path):
    client = _client(tmp_path)
    r = client.post("/query", json={"prompt": "q"})                 # neither
    assert r.status_code == 422
    r = client.post("/query", json={"prompt": "q", "corpus": "c", "document_id": 1})
    assert r.status_code == 422                                     # both


def test_single_document_query_returns_attributed_hits(tmp_path, monkeypatch):
    client = _client(tmp_path)
    with db.SessionLocal() as s:
        c = _corpus(s); d = _indexed_doc(s, c); doc_id = d.id
    monkeypatch.setattr(query_api, "_open_pipeline", lambda settings: (lambda p: _FakeCorpus()))
    r = client.post("/query", json={"prompt": "q", "document_id": doc_id})
    assert r.status_code == 200, r.text
    hits = r.json()["hits"]
    assert hits and all(h["pipeline"] == "solo_docling" for h in hits)


def test_single_document_query_404_for_missing_doc(tmp_path):
    client = _client(tmp_path)
    r = client.post("/query", json={"prompt": "q", "document_id": 9999})
    assert r.status_code == 404
