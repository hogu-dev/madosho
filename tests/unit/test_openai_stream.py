import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from madosho.core.types import Chunk, Hit
from madosho_server import db, membership, pipeline_cache, query_core, query_api


class _FakeCorpus:
    def query(self, text):
        chunk = Chunk(id="c1", doc_id="d1", text="ctx", page=1,
                      metadata={"source": "/fs/a.pdf"})
        return [Hit(chunk_id="c1", score=1.0, source_index="rrf", chunk=chunk)]


def _chunk(content, finish=None):
    return SimpleNamespace(model_dump=lambda: {
        "id": "chatcmpl-x", "object": "chat.completion.chunk", "created": 0,
        "model": "upstream-model",
        "choices": [{"index": 0, "delta": {"content": content},
                     "finish_reason": finish}],
    })


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'st.db'}")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))


def _seed_vm():
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
        s.add(db.VirtualModel(name="contracts@local", corpus_id=c.id,
                              provider="ollama", model="llama3.1"))
        s.commit()


def test_chat_completion_stream(env, monkeypatch):
    def fake_complete(**kw):
        assert kw["stream"] is True
        return iter([_chunk("Hello "), _chunk("world", finish="stop")])

    with TestClient(query_api.app) as client:
        _seed_vm()
        monkeypatch.setattr(pipeline_cache, "corpus_for", lambda p, d: _FakeCorpus())
        monkeypatch.setattr(query_core.llm, "complete", fake_complete)

        r = client.post("/v1/chat/completions", json={
            "model": "contracts@local",
            "messages": [{"role": "user", "content": "term?"}],
            "stream": True})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")

        # Parse SSE data lines
        datas = [line[len("data: "):] for line in r.text.splitlines()
                 if line.startswith("data: ")]
        assert datas[-1] == "[DONE]"
        chunks = [json.loads(d) for d in datas[:-1]]
        # every chunk reports the virtual model name
        assert all(c["model"] == "contracts@local" for c in chunks)
        # provider deltas + one citations delta
        contents = [c["choices"][0]["delta"].get("content", "") for c in chunks]
        assert "Hello " in contents and "world" in contents
        assert any("Sources:" in c for c in contents)
