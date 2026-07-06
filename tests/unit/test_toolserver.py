"""Tool-server endpoint tests. Each POST drives madosho_cli.core, whose urllib
is faked - so we assert the endpoint marshals to the right retrieval HTTP call AND
returns the core result the model will read."""
from __future__ import annotations

import json
import urllib.request

import pytest
from fastapi.testclient import TestClient

from madosho_toolserver.app import app


class _Resp:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHttp:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, req, *a, **kw):
        url = req.full_url
        body = json.loads(req.data.decode()) if getattr(req, "data", None) else None
        self.calls.append((req.get_method(), url, body))
        for key in sorted(self.routes, key=len, reverse=True):
            if key in url:
                val = self.routes[key]
                if isinstance(val, Exception):
                    raise val
                return _Resp(val)
        raise AssertionError(f"unexpected URL: {url}")


@pytest.fixture
def fake_http(monkeypatch):
    def install(routes):
        fh = FakeHttp(routes)
        monkeypatch.setattr(urllib.request, "urlopen", fh)
        return fh
    return install


def test_health():
    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_search_endpoint_marshals_to_retrieval_only_query(fake_http):
    fh = fake_http({"/query": {"hits": [{"text": "t", "score": 1.0,
                                         "citation": "a.pdf p.1"}]}})
    r = TestClient(app).post("/search", json={"corpus": "aero", "query": "x"})
    assert r.status_code == 200
    assert r.json()["hits"][0]["citation"] == "a.pdf p.1"
    method, url, body = fh.calls[0]
    assert method == "POST" and url.endswith("/query")
    assert body == {"corpus": "aero", "prompt": "x"}   # no llm field -> retrieval only


def test_list_documents_endpoint_resolves_corpus(fake_http):
    fh = fake_http({
        "/corpora": [{"id": 2, "name": "aero", "config": {}}],
        "/corpora/2/documents": [{"id": 3, "filename": "a.pdf",
                                  "status": "indexed", "selected_pipeline_id": None}],
    })
    r = TestClient(app).post("/list-documents", json={"corpus": "aero"})
    assert r.json()["documents"][0]["id"] == 3
    assert any("/corpora/2/documents" in c[1] for c in fh.calls)


def test_get_doc_endpoint(fake_http):
    fake_http({
        "/documents/5/pipelines": [{"id": 10, "name": "p", "effective": True,
                                    "status": "indexed"}],
        "/pipelines/10/artifacts": {"document_id": 5, "chunks": [
            {"text": "first", "position": 0}], "tables": []},
    })
    r = TestClient(app).post("/get-doc", json={"document_id": 5})
    assert r.json()["text"] == "first"
    assert r.json()["pipeline_id"] == 10


def test_search_doc_endpoint_scopes_by_document_id(fake_http):
    fh = fake_http({"/query": {"hits": [{"text": "t", "score": 1.0,
                                         "citation": "a.pdf p.1"}]}})
    r = TestClient(app).post("/search-doc", json={"document_id": 3, "query": "x"})
    assert r.status_code == 200
    assert r.json()["hits"][0]["citation"] == "a.pdf p.1"
    method, url, body = fh.calls[0]
    assert method == "POST" and url.endswith("/query")
    assert body == {"document_id": 3, "prompt": "x"}   # scoped by id, no corpus


def test_list_pipelines_endpoint_by_document(fake_http):
    fake_http({"/documents/5/pipelines": [
        {"id": 9, "name": "wav_docling", "rating": 0.8, "status": "indexed",
         "effective": True}]})
    r = TestClient(app).post("/list-pipelines", json={"document_id": 5})
    assert r.status_code == 200
    assert r.json()["pipelines"][0]["name"] == "wav_docling"


def test_list_pipelines_endpoint_requires_one_scope(fake_http):
    fake_http({})
    r = TestClient(app).post("/list-pipelines", json={})
    assert r.status_code == 502   # core CliError -> clean 502
    assert "exactly one" in r.json()["detail"]


def test_list_corpora_endpoint(fake_http):
    fake_http({"/corpora": [{"id": 1, "name": "a", "config": {}}]})
    r = TestClient(app).post("/list-corpora", json={})
    assert r.json() == {"corpora": [{"id": 1, "name": "a"}]}


def test_core_error_becomes_502(fake_http):
    # unknown corpus -> core raises CliError -> endpoint maps to a clean 502
    fake_http({"/corpora": [{"id": 1, "name": "a", "config": {}}]})
    r = TestClient(app).post("/list-documents", json={"corpus": "ghost"})
    assert r.status_code == 502
    assert "corpus not found" in r.json()["detail"]


def test_cors_headers_present_for_browser_frontend():
    """A browser frontend (Open WebUI's "Manage Tool Servers") fetches /openapi.json
    cross-origin (e.g. :3000 -> :8088). Without CORS the browser blocks the response
    and registration fails with a vague "failed to connect". Assert the middleware
    answers both a simple cross-origin GET and a preflight with a permissive origin."""
    client = TestClient(app)
    r = client.get("/openapi.json", headers={"origin": "http://localhost:3000"})
    assert r.headers.get("access-control-allow-origin") == "*"
    pre = client.options(
        "/search",
        headers={
            "origin": "http://localhost:3000",
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type",
        },
    )
    assert pre.status_code == 200
    assert pre.headers.get("access-control-allow-origin") == "*"
