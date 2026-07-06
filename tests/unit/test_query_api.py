import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from madosho.core.types import Chunk, Hit
from madosho_server import db, membership, pipeline_cache, query_core, query_api


def _hit(text, page=1, source="/fs/a.pdf", cid="c1"):
    chunk = Chunk(id=cid, doc_id="kd", text=text, page=page, position=0,
                  metadata={"source": source})
    return Hit(chunk_id=cid, score=1.0, source_index="rrf", chunk=chunk)


class _FakeCorpus:
    def __init__(self, hits):
        self._hits = hits

    def query(self, text):
        return self._hits


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'q.db'}")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))


def _seed(name="demo", pipeline_name="demo_docling"):
    """A corpus + one indexed document + one indexed (highest-rated) pipeline."""
    with db.SessionLocal() as s:
        c = db.Corpus(name=name, config={"corpus": name, "query": []})
        s.add(c); s.commit(); s.refresh(c)
        d = db.Document(filename="a.pdf", content_hash="h",
                        file_uri="u", mimetype="application/pdf", status="indexed",
                        kernel_doc_id="kd")
        s.add(d); s.commit(); s.refresh(d)
        membership.add_membership(s, d.id, c.id); s.commit()
        p = db.Pipeline(document_id=d.id, name=pipeline_name,
                        config={"corpus": name}, collection=f"madosho_{name}_1",
                        status="indexed")
        s.add(p); s.commit(); s.refresh(p)
        return c.id, d.id, p.id


def test_query_without_llm_returns_hits(env, monkeypatch):
    with TestClient(query_api.app) as client:
        _seed()
        monkeypatch.setattr(pipeline_cache, "corpus_for",
                            lambda p, d: _FakeCorpus([_hit("hello world", page=2)]))
        r = client.post("/query", json={"corpus": "demo", "prompt": "hi"})
        assert r.status_code == 200
        body = r.json()
        assert "answer" not in body
        assert body["hits"][0]["text"] == "hello world"
        assert body["hits"][0]["page"] == 2
        assert body["hits"][0]["pipeline"] == "demo_docling"
        assert body["hits"][0]["document_id"] is not None


def test_query_unknown_corpus_404(env):
    with TestClient(query_api.app) as client:
        r = client.post("/query", json={"corpus": "nope", "prompt": "hi"})
        assert r.status_code == 404


def test_query_with_llm_returns_answer(env, monkeypatch):
    from types import SimpleNamespace

    def fake_complete(messages, provider, model, settings, stream=False):
        msg = SimpleNamespace(content="The term is two years.")
        usage = SimpleNamespace(model_dump=lambda: {"total_tokens": 11})
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=usage)

    with TestClient(query_api.app) as client:
        _seed()
        monkeypatch.setattr(pipeline_cache, "corpus_for",
                            lambda p, d: _FakeCorpus([_hit("Term: two years", page=1)]))
        monkeypatch.setattr(query_core.llm, "complete", fake_complete)
        r = client.post("/query", json={"corpus": "demo", "prompt": "term?",
                                        "llm": "ollama:llama3.1"})
        assert r.status_code == 200
        body = r.json()
        assert "The term is two years." in body["answer"]
        assert "Sources:" in body["answer"]
        assert body["citations"][0]["citation"] == "a.pdf p.1"
        assert body["citations"][0]["pipeline"] == "demo_docling"
        assert body["usage"] == {"total_tokens": 11}
        roles = [m["role"] for m in body["messages"]]
        assert roles == ["system", "user"]
        assert "Term: two years" in body["messages"][0]["content"]
        assert body["messages"][-1]["content"] == "term?"


def test_query_with_bad_llm_string_422(env, monkeypatch):
    with TestClient(query_api.app) as client:
        _seed()
        monkeypatch.setattr(pipeline_cache, "corpus_for",
                            lambda p, d: _FakeCorpus([_hit("x")]))
        r = client.post("/query", json={"corpus": "demo", "prompt": "q",
                                        "llm": "no-colon"})
        assert r.status_code == 422


def test_query_pipeline_override_selects_named_index(env, monkeypatch):
    with TestClient(query_api.app) as client:
        cid, did, pid = _seed()
        with db.SessionLocal() as s:
            alt = db.Pipeline(document_id=did, name="demo_olmocr",
                              config={"corpus": "demo"}, collection="madosho_demo_2",
                              status="indexed")
            s.add(alt); s.commit()
        monkeypatch.setattr(pipeline_cache, "corpus_for",
                            lambda p, d: _FakeCorpus([_hit(f"from {p.name}", cid=p.name)]))
        r = client.post("/query", json={"corpus": "demo", "prompt": "hi",
                                        "pipelines": ["demo_olmocr"]})
        assert r.status_code == 200
        assert r.json()["hits"][0]["pipeline"] == "demo_olmocr"


def test_query_unknown_pipeline_400(env, monkeypatch):
    with TestClient(query_api.app) as client:
        _seed()
        monkeypatch.setattr(pipeline_cache, "corpus_for",
                            lambda p, d: _FakeCorpus([_hit("x")]))
        r = client.post("/query", json={"corpus": "demo", "prompt": "hi",
                                        "pipelines": ["ghost"]})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# _resolve_answer_llm unit tests (Task 6)
# ---------------------------------------------------------------------------

def _mk_db(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path / 'r.db'}")
    db.create_all()


def test_resolve_answer_llm_name_match(tmp_path, monkeypatch):
    """Registry name -> per-endpoint creds (api_base + key from env)."""
    _mk_db(tmp_path)
    monkeypatch.setenv("MY_KEY", "secret123")
    with db.SessionLocal() as s:
        s.add(db.LlmEndpoint(name="gemma4-local", provider="openai", model="gemma-4-e4b",
                             api_base="http://h:8081/v1", key_env_var="MY_KEY",
                             is_default=True))
        s.commit()
    from madosho_server.settings import Settings
    settings = Settings.from_env()
    with db.SessionLocal() as s:
        result = query_api._resolve_answer_llm(s, settings, "gemma4-local")
    assert result is not None
    provider, model, creds = result
    assert provider == "openai"
    assert model == "gemma-4-e4b"
    assert creds.llm_api_base == "http://h:8081/v1"
    assert creds.llm_api_key == "secret123"


def test_resolve_answer_llm_legacy_provider_model(tmp_path):
    """Legacy 'provider:model' string -> same global settings object."""
    _mk_db(tmp_path)
    from madosho_server.settings import Settings
    settings = Settings.from_env()
    with db.SessionLocal() as s:
        result = query_api._resolve_answer_llm(s, settings, "openai:gpt-x")
    assert result is not None
    provider, model, creds = result
    assert provider == "openai"
    assert model == "gpt-x"
    assert creds is settings


def test_resolve_answer_llm_garbage_returns_none(tmp_path):
    """Garbage string (no colon, no registry match) -> None."""
    _mk_db(tmp_path)
    from madosho_server.settings import Settings
    settings = Settings.from_env()
    with db.SessionLocal() as s:
        result = query_api._resolve_answer_llm(s, settings, "nonsense")
    assert result is None


def test_query_plane_openapi_names_response_models():
    schema = query_api.app.openapi()
    comps = schema["components"]["schemas"]
    assert "Citation" in comps
    assert "QueryHitsResponse" in comps
    assert "QueryAnswerResponse" in comps
    assert "ModelsResponse" in comps
    assert "PipelineCard" in comps


def test_error_models_documented_in_openapi():
    schema = query_api.app.openapi()
    comps = schema["components"]["schemas"]
    assert "ErrorResponse" in comps          # native {"detail": ...}
    assert "OpenAIErrorResponse" in comps    # shim {"error": {...}}


def test_native_query_error_is_detail_shaped(env):
    with TestClient(query_api.app) as client:
        r = client.post("/query", json={"corpus": "nope", "prompt": "hi"})
        assert r.status_code == 404
        assert "detail" in r.json()          # native plane convention


def test_shim_error_is_openai_shaped(env):
    with TestClient(query_api.app) as client:
        r = client.post("/v1/chat/completions",
                        json={"model": "ghost", "messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 404
        assert r.json()["error"]["type"] == "invalid_request_error"   # shim convention
