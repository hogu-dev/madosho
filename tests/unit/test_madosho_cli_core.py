"""Direct tests of madosho_cli.core - the pure orchestration the CLI AND the
OpenAPI tool server share. Same FakeHttp routing as test_madosho_cli.py."""
from __future__ import annotations

import json
import urllib.request

import pytest

from madosho_cli import core, http


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


def test_core_list_corpora(fake_http):
    fake_http({"/corpora": [{"id": 1, "name": "a", "config": {}},
                            {"id": 2, "name": "b", "config": {}}]})
    assert core.list_corpora() == {"corpora": [{"id": 1, "name": "a"},
                                               {"id": 2, "name": "b"}]}


def test_core_search_truncates_and_posts_retrieval_only(fake_http):
    fh = fake_http({"/query": {"hits": [{"text": f"t{i}", "score": 1.0,
                                         "citation": f"a.pdf p.{i}"} for i in range(10)]}})
    out = core.search("aerospace", "sensor failure", top_k=3)
    assert len(out["hits"]) == 3
    method, url, body = fh.calls[0]
    assert method == "POST" and url.endswith("/query")
    assert body == {"corpus": "aerospace", "prompt": "sensor failure"}


def test_core_search_pipeline_passthrough(fake_http):
    fh = fake_http({"/query": {"hits": []}})
    core.search("aerospace", "q", pipeline="afti_nodocling")
    assert fh.calls[0][2]["pipelines"] == ["afti_nodocling"]


def test_core_search_document_scopes_by_id(fake_http):
    fh = fake_http({"/query": {"hits": [{"text": f"t{i}", "score": 1.0,
                                         "citation": f"a.pdf p.{i}"} for i in range(10)]}})
    out = core.search_document(3, "sensor failure", top_k=2)
    assert len(out["hits"]) == 2
    method, url, body = fh.calls[0]
    # same retrieval-only POST as search(), but scoped by document_id (no corpus)
    assert method == "POST" and url.endswith("/query")
    assert body == {"document_id": 3, "prompt": "sensor failure"}


def test_core_search_document_pipeline_passthrough(fake_http):
    fh = fake_http({"/query": {"hits": []}})
    core.search_document(3, "q", pipeline="afti_nodocling")
    assert fh.calls[0][2]["pipelines"] == ["afti_nodocling"]


def test_core_list_pipelines_by_document(fake_http):
    fake_http({"/documents/5/pipelines": [
        {"id": 9, "name": "wav_docling", "rating": 0.8, "status": "indexed",
         "effective": False},
        {"id": 10, "name": "wav_nodocling", "rating": None, "status": "building",
         "effective": True}]})
    out = core.list_pipelines(document_id=5)
    assert out["document_id"] == 5
    assert out["pipelines"][0] == {"id": 9, "name": "wav_docling", "rating": 0.8,
                                   "status": "indexed", "effective": False}
    assert out["pipelines"][1]["effective"] is True


def test_core_list_pipelines_by_corpus(fake_http):
    fake_http({"/corpora/aero/pipelines": [
        {"name": "afti_docling", "document_id": 3, "rating": 0.9, "status": "indexed",
         "effective": True}]})
    out = core.list_pipelines(corpus="aero")
    assert out["corpus"] == "aero"
    assert out["pipelines"][0] == {"name": "afti_docling", "document_id": 3,
                                   "rating": 0.9, "status": "indexed", "effective": True}


def test_core_list_pipelines_requires_exactly_one_scope():
    with pytest.raises(http.CliError, match="exactly one"):
        core.list_pipelines()
    with pytest.raises(http.CliError, match="exactly one"):
        core.list_pipelines(corpus="aero", document_id=5)


def test_core_list_documents_resolves_name(fake_http):
    fake_http({
        "/corpora": [{"id": 2, "name": "aero", "config": {}}],
        "/corpora/2/documents": [
            {"id": 3, "filename": "afti.pdf", "status": "indexed",
             "selected_pipeline_id": None}],
    })
    out = core.list_documents("aero")
    assert out["corpus"] == "aero"
    assert out["documents"][0]["id"] == 3


def test_core_list_documents_unknown_corpus_raises(fake_http):
    fake_http({"/corpora": [{"id": 2, "name": "aero", "config": {}}]})
    with pytest.raises(http.CliError, match="corpus not found"):
        core.list_documents("nope")


def test_core_get_doc_effective_joins_in_position_order(fake_http):
    fake_http({
        "/documents/5/pipelines": [
            {"id": 10, "name": "wav_nodocling", "effective": True, "status": "indexed"}],
        "/pipelines/10/artifacts": {"document_id": 5, "chunks": [
            {"id": "c2", "text": "second", "position": 1},
            {"id": "c1", "text": "first", "position": 0}], "tables": []},
    })
    out = core.get_doc(5)
    assert out["pipeline"] == "wav_nodocling"
    assert out["pipeline_id"] == 10
    assert out["text"] == "first\n\nsecond"
    assert out["char_count"] == len("first\n\nsecond")


def test_core_get_doc_no_effective_raises(fake_http):
    fake_http({"/documents/7/pipelines": [
        {"id": 1, "name": "x", "effective": False, "status": "building"}]})
    with pytest.raises(http.CliError, match="no effective pipeline"):
        core.get_doc(7)
