# FALLBACK PATH: ASGITransport is async-only (handle_async_request); the sync
# openai.OpenAI client drives httpx.Client.send() which calls handle_request
# (sync) — a method ASGITransport does not implement. This is a pure
# environmental limitation (httpx.ASGITransport design), NOT a wire-format
# bug in our shim.
#
# Fallback per plan: validate wire shapes using the SDK's own pydantic models
# (openai.types.chat.ChatCompletion, ChatCompletionChunk) driven by
# fastapi.testclient.TestClient (which runs the ASGI app synchronously).
# This still proves our shim emits exactly the shapes the openai SDK accepts.

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from openai.types import Model
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from madosho.core.types import Chunk, Hit
from madosho_server import db, membership, pipeline_cache, query_core, query_api


class _FakeCorpus:
    def query(self, text):
        chunk = Chunk(id="c1", doc_id="d1", text="ctx", page=1,
                      metadata={"source": "/fs/a.pdf"})
        return [Hit(chunk_id="c1", score=1.0, source_index="rrf", chunk=chunk)]


def _completion_obj(content="The term is two years."):
    return SimpleNamespace(model_dump=lambda: {
        "id": "chatcmpl-x", "object": "chat.completion", "created": 0,
        "model": "upstream-model",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    })


def _stream_chunks():
    def chunk(content, finish=None):
        return SimpleNamespace(model_dump=lambda content=content, finish=finish: {
            "id": "chatcmpl-x", "object": "chat.completion.chunk", "created": 0,
            "model": "upstream-model",
            "choices": [{"index": 0, "delta": {"content": content},
                         "finish_reason": finish}]})
    return iter([chunk("The term "), chunk("is two years.", finish="stop")])


@pytest.fixture
def tc(tmp_path, monkeypatch):
    # Configure the engine + schema directly (TestClient does not run lifespan).
    db.configure_engine(f"sqlite:///{tmp_path / 'contract.db'}")
    db.create_all()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'contract.db'}")
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
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
    monkeypatch.setattr(pipeline_cache, "corpus_for", lambda p, d: _FakeCorpus())
    return TestClient(query_api.app)


def test_openai_client_lists_models(tc):
    """Wire shape of /v1/models validates against openai.types.Model."""
    r = tc.get("/v1/models")
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "list"
    # Each entry must satisfy the openai SDK's Model schema
    models = [Model.model_validate(m) for m in body["data"]]
    ids = [m.id for m in models]
    assert "contracts@local" in ids


def test_openai_client_non_stream(tc, monkeypatch):
    """Non-streaming response validates against openai.types.chat.ChatCompletion."""
    monkeypatch.setattr(query_core.llm, "complete", lambda **kw: _completion_obj())
    r = tc.post("/v1/chat/completions", json={
        "model": "contracts@local",
        "messages": [{"role": "user", "content": "term?"}]})
    assert r.status_code == 200
    # This will raise if the shape doesn't match the SDK's pydantic schema
    obj = ChatCompletion.model_validate(r.json())
    assert obj.model == "contracts@local"
    content = obj.choices[0].message.content
    assert "The term is two years." in content
    assert "Sources:" in content


def test_openai_client_stream(tc, monkeypatch):
    """Streaming SSE chunks each validate against ChatCompletionChunk."""
    monkeypatch.setattr(query_core.llm, "complete", lambda **kw: _stream_chunks())
    r = tc.post("/v1/chat/completions", json={
        "model": "contracts@local",
        "messages": [{"role": "user", "content": "term?"}],
        "stream": True})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    datas = [line[len("data: "):] for line in r.text.splitlines()
             if line.startswith("data: ")]
    assert datas[-1] == "[DONE]"
    # Each data line (except [DONE]) must validate against ChatCompletionChunk
    chunks = [ChatCompletionChunk.model_validate(json.loads(d)) for d in datas[:-1]]
    text = "".join(c.choices[0].delta.content or "" for c in chunks if c.choices)
    assert "The term is two years." in text
    assert "Sources:" in text
