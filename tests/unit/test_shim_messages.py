"""Mode A (the shim) coverage for the requests Open WebUI actually sends:
a system prompt + multi-turn history. Locks that retrieval keys on the LAST user
turn and that the client's system + history are preserved into generation. Also
pins the model-card fields and the provider-not-configured envelope."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from madosho.core.types import Chunk, Hit
from madosho_server import db, llm, membership, pipeline_cache, query_core, query_api


def _completion_obj(content="ok"):
    return SimpleNamespace(model_dump=lambda: {
        "id": "x", "object": "chat.completion", "created": 0, "model": "up",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})


class _RecordingCorpus:
    def __init__(self):
        self.queried_with = None

    def query(self, text):
        self.queried_with = text
        chunk = Chunk(id="c1", doc_id="d1", text="ctx", page=1,
                      metadata={"source": "/fs/a.pdf"})
        return [Hit(chunk_id="c1", score=1.0, source_index="rrf", chunk=chunk)]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 's.db'}")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))


def _seed_vm(name="contracts@local"):
    with db.SessionLocal() as s:
        c = db.Corpus(name="contracts", config={"corpus": "contracts", "query": []})
        s.add(c); s.commit(); s.refresh(c)
        d = db.Document(filename="a.pdf", content_hash="h", file_uri="u",
                        mimetype="application/pdf", status="indexed", kernel_doc_id="kd")
        s.add(d); s.commit(); s.refresh(d)
        membership.add_membership(s, d.id, c.id); s.commit()
        s.add(db.Pipeline(document_id=d.id, name="contracts_docling",
                          config={"corpus": "contracts"}, collection="madosho_contracts_1",
                          status="indexed")); s.commit()
        s.add(db.VirtualModel(name=name, corpus_id=c.id, provider="ollama",
                              model="llama3.1", template=None)); s.commit()


def test_retrieval_uses_last_user_turn_with_system_and_history(env, monkeypatch):
    with TestClient(query_api.app) as client:
        _seed_vm()
        corpus = _RecordingCorpus()
        monkeypatch.setattr(pipeline_cache, "corpus_for", lambda p, d: corpus)
        captured = {}

        def fake_complete(**kw):
            captured["messages"] = kw["messages"]
            return _completion_obj()

        monkeypatch.setattr(query_core.llm, "complete", fake_complete)
        r = client.post("/v1/chat/completions", json={"model": "contracts@local",
            "messages": [
                {"role": "system", "content": "Be terse."},
                {"role": "user", "content": "first question"},
                {"role": "assistant", "content": "first answer"},
                {"role": "user", "content": "the real query"}]})
        assert r.status_code == 200
        # retrieval keyed on the LAST user turn, not the system or an earlier turn
        assert corpus.queried_with == "the real query"
        # generation received the client's system + full history (nothing dropped)
        sent = captured["messages"]
        assert any(m["role"] == "system" and m["content"] == "Be terse." for m in sent)
        assert [m["content"] for m in sent if m["role"] == "user"] == \
               ["first question", "the real query"]


def test_provider_not_configured_returns_openai_400(env, monkeypatch):
    with TestClient(query_api.app) as client:
        _seed_vm()
        monkeypatch.setattr(pipeline_cache, "corpus_for", lambda p, d: _RecordingCorpus())

        def _boom(**kw):
            raise llm.ProviderNotConfigured("no provider")

        monkeypatch.setattr(query_core.llm, "complete", _boom)
        r = client.post("/v1/chat/completions", json={"model": "contracts@local",
            "messages": [{"role": "user", "content": "x"}]})
        assert r.status_code == 400
        assert r.json()["error"]["type"] == "invalid_request_error"


def test_model_card_is_openai_complete(env):
    with TestClient(query_api.app) as client:
        _seed_vm()
        card = client.get("/v1/models").json()["data"][0]
        assert set(card) >= {"id", "object", "created", "owned_by"}
        assert card["object"] == "model"
        assert card["owned_by"] == "madosho"
