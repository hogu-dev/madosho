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

    def fake_complete(messages, provider, model, settings, stream=False,
                      reasoning_effort=None):
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


def test_query_with_llm_endpoint_reasoning_effort_forwarded(env, monkeypatch):
    """A /query answer resolved via a registry endpoint NAME forwards that
    endpoint's own reasoning_effort default into the provider call (Task 10
    follow-up: query was the one path not yet threading it through)."""
    from types import SimpleNamespace

    captured = {}

    def fake_complete(messages, provider, model, settings, stream=False,
                      reasoning_effort=None):
        captured["reasoning_effort"] = reasoning_effort
        msg = SimpleNamespace(content="The term is two years.")
        usage = SimpleNamespace(model_dump=lambda: {"total_tokens": 11})
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=usage)

    with TestClient(query_api.app) as client:
        _seed()
        with db.SessionLocal() as s:
            s.add(db.LlmEndpoint(name="gemma4-local", provider="ollama", model="llama3.1",
                                 api_base="http://h:8081/v1", reasoning_effort="low",
                                 is_default=True))
            s.commit()
        monkeypatch.setattr(pipeline_cache, "corpus_for",
                            lambda p, d: _FakeCorpus([_hit("Term: two years", page=1)]))
        monkeypatch.setattr(query_core.llm, "complete", fake_complete)
        r = client.post("/query", json={"corpus": "demo", "prompt": "term?",
                                        "llm": "gemma4-local"})
        assert r.status_code == 200
        assert captured["reasoning_effort"] == "low"


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
    provider, model, creds, effort = result
    assert provider == "openai"
    assert model == "gemma-4-e4b"
    assert creds.llm_api_base == "http://h:8081/v1"
    assert creds.llm_api_key == "secret123"
    assert effort is None


def test_resolve_answer_llm_legacy_provider_model(tmp_path):
    """Legacy 'provider:model' string -> same global settings object."""
    _mk_db(tmp_path)
    from madosho_server.settings import Settings
    settings = Settings.from_env()
    with db.SessionLocal() as s:
        result = query_api._resolve_answer_llm(s, settings, "openai:gpt-x")
    assert result is not None
    provider, model, creds, effort = result
    assert provider == "openai"
    assert model == "gpt-x"
    assert creds is settings
    assert effort is None


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


# ---------------------------------------------------------------------------
# Provenance labels on hits (Stage D, Task 12)
# ---------------------------------------------------------------------------

def test_query_labels_generated_document_hits(env, monkeypatch):
    with TestClient(query_api.app) as client:
        _cid, did, _pid = _seed()
        with db.SessionLocal() as s:
            d = s.get(db.Document, did)
            d.origin = "generated"
            d.origin_meta = {"goal": "find_vuln", "version": 2}
            s.commit()
        monkeypatch.setattr(pipeline_cache, "corpus_for",
                            lambda p, d: _FakeCorpus([_hit("evidence", page=1)]))
        r = client.post("/query", json={"corpus": "demo", "prompt": "hi"})
        hit = r.json()["hits"][0]
        assert hit["origin"] == "generated"
        assert hit["citation"].endswith("[generated: find_vuln v2]")


def test_query_source_document_hits_unlabeled(env, monkeypatch):
    with TestClient(query_api.app) as client:
        _seed()                                   # origin defaults to source
        monkeypatch.setattr(pipeline_cache, "corpus_for",
                            lambda p, d: _FakeCorpus([_hit("plain", page=1)]))
        r = client.post("/query", json={"corpus": "demo", "prompt": "hi"})
        hit = r.json()["hits"][0]
        assert hit["origin"] == "source"
        assert "[generated" not in hit["citation"]


# -- KB fused semantic search (query plane) ---------------------------------

def _seed_kb(base_dir):
    """A corpus + KB row + two pages on disk; returns kb_id."""
    from madosho_server import kb_store
    with db.SessionLocal() as s:
        c = db.Corpus(name="demo", config={"corpus": "demo", "query": []})
        s.add(c); s.commit(); s.refresh(c)
        kb = db.Kb(corpus_id=c.id, name="Notes", slug="notes")
        s.add(kb); s.commit(); s.refresh(kb)
        kb_id = kb.id
    root = kb_store.create_kb(base_dir, kb_id, "Notes")
    kb_store.add_page(root, type="concept", title="AFTI", description="flight",
                      body="digital flight control")
    kb_store.add_page(root, type="concept", title="Saturn V", description="rocket",
                      body="rocket engine")
    return kb_id


def _stub_semantic(monkeypatch, hits):
    """Stub the query plane's semantic lane so no qdrant/model is needed."""
    from madosho_server import kb_index

    class _FakeStore:
        class native:
            @staticmethod
            def collection_exists(name):
                return True

    monkeypatch.setattr(kb_index, "open_store", lambda url, kid: _FakeStore())
    monkeypatch.setattr(kb_index, "get_embedder", lambda: object())
    monkeypatch.setattr(kb_index, "search", lambda store, emb, q, k=20: hits)


def test_kb_search_fuses_lexical_and_semantic(env, monkeypatch, tmp_path):
    monkeypatch.setenv("KB_DIR", str(tmp_path / "kbs"))
    with TestClient(query_api.app) as client:
        kb_id = _seed_kb(str(tmp_path / "kbs"))
        # semantic surfaces 'saturn-v', which the lexical scan for "flight" misses
        sem = [_hit_kb("saturn-v", "Saturn V", "rocket")]
        _stub_semantic(monkeypatch, sem)
        r = client.get(f"/kbs/{kb_id}/search", params={"q": "flight"})
        assert r.status_code == 200
        slugs = {p["slug"] for p in r.json()}
        assert "afti" in slugs          # lexical match on "flight"
        assert "saturn-v" in slugs      # semantic-only match, unioned in


def test_kb_search_falls_back_to_lexical_when_unindexed(env, monkeypatch, tmp_path):
    from madosho_server import kb_index
    monkeypatch.setenv("KB_DIR", str(tmp_path / "kbs"))
    with TestClient(query_api.app) as client:
        kb_id = _seed_kb(str(tmp_path / "kbs"))

        class _NoColl:
            class native:
                @staticmethod
                def collection_exists(name):
                    return False
        monkeypatch.setattr(kb_index, "open_store", lambda url, kid: _NoColl())
        r = client.get(f"/kbs/{kb_id}/search", params={"q": "flight"})
        assert r.status_code == 200
        assert [p["slug"] for p in r.json()] == ["afti"]   # lexical only


def test_kb_search_unknown_kb_404(env, tmp_path, monkeypatch):
    monkeypatch.setenv("KB_DIR", str(tmp_path / "kbs"))
    with TestClient(query_api.app) as client:
        assert client.get("/kbs/999/search", params={"q": "x"}).status_code == 404


def _hit_kb(slug, title, description):
    from madosho.core.types import Chunk, Hit
    ch = Chunk(id=slug, doc_id=slug, text="",
               metadata={"slug": slug, "type": "concept", "title": title,
                         "description": description})
    return Hit(chunk_id=slug, score=0.9, source_index="dense", chunk=ch)
