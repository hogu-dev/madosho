from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from madosho.core.types import Chunk, Hit
from madosho_server import db, membership, pipeline_cache, query_core, query_api


def _hit(text="ctx", page=1, source="/fs/a.pdf"):
    chunk = Chunk(id="c1", doc_id="d1", text=text, page=page,
                  metadata={"source": source})
    return Hit(chunk_id="c1", score=1.0, source_index="rrf", chunk=chunk)


class _FakeCorpus:
    def query(self, text):
        return [_hit()]


def _completion_obj(content="Hello from the model."):
    return SimpleNamespace(model_dump=lambda: {
        "id": "chatcmpl-x", "object": "chat.completion", "created": 0,
        "model": "upstream-model",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    })


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 's.db'}")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))


def _seed_vm(name="contracts@local"):
    """Corpus + indexed document + indexed pipeline + virtual model."""
    with db.SessionLocal() as s:
        c = db.Corpus(name="contracts", config={"corpus": "contracts", "query": []})
        s.add(c); s.commit(); s.refresh(c)
        d = db.Document(filename="a.pdf", content_hash="h",
                        file_uri="u", mimetype="application/pdf", status="indexed",
                        kernel_doc_id="kd")
        s.add(d); s.commit(); s.refresh(d)
        membership.add_membership(s, d.id, c.id); s.commit()
        p = db.Pipeline(document_id=d.id, name="contracts_docling",
                        config={"corpus": "contracts"}, collection="madosho_contracts_1",
                        status="indexed")
        s.add(p); s.commit()
        s.add(db.VirtualModel(name=name, corpus_id=c.id, provider="ollama",
                              model="llama3.1", template=None))
        s.commit()


def test_list_models(env):
    with TestClient(query_api.app) as client:
        _seed_vm()
        body = client.get("/v1/models").json()
        assert body["object"] == "list"
        assert body["data"][0]["id"] == "contracts@local"
        assert body["data"][0]["object"] == "model"


def test_chat_completion_non_stream(env, monkeypatch):
    with TestClient(query_api.app) as client:
        _seed_vm()
        monkeypatch.setattr(pipeline_cache, "corpus_for", lambda p, d: _FakeCorpus())
        monkeypatch.setattr(query_core.llm, "complete",
                            lambda **kw: _completion_obj())
        r = client.post("/v1/chat/completions", json={
            "model": "contracts@local",
            "messages": [{"role": "user", "content": "term?"}]})
        assert r.status_code == 200
        body = r.json()
        assert body["object"] == "chat.completion"
        assert body["model"] == "contracts@local"          # reports the virtual model
        content = body["choices"][0]["message"]["content"]
        assert "Hello from the model." in content
        assert "Sources:" in content                        # citations appended


def test_chat_completion_unknown_model_envelope(env):
    with TestClient(query_api.app) as client:
        r = client.post("/v1/chat/completions", json={
            "model": "nope", "messages": [{"role": "user", "content": "x"}]})
        assert r.status_code == 404
        assert r.json()["error"]["message"]                 # OpenAI error envelope
        assert r.json()["error"]["type"] == "invalid_request_error"


def test_chat_completion_provider_error_502(env, monkeypatch):
    with TestClient(query_api.app) as client:
        _seed_vm()
        monkeypatch.setattr(pipeline_cache, "corpus_for", lambda p, d: _FakeCorpus())

        def _boom(**kw):
            raise RuntimeError("timeout")

        monkeypatch.setattr(query_core.llm, "complete", _boom)
        r = client.post("/v1/chat/completions", json={
            "model": "contracts@local",
            "messages": [{"role": "user", "content": "x"}]})
        assert r.status_code == 502
        assert r.json()["error"]["type"] == "api_error"
        assert r.json()["error"]["message"]
