"""dispatch() routes an MCP tool call to madosho_cli.core - the shared seam the
CLI and the OpenAPI tool server also use. core is stubbed (no live server)."""
from __future__ import annotations

import pytest

from madosho_cli import http
from madosho_mcp import server


def test_dispatch_search_routes_to_core(monkeypatch):
    seen = {}

    def fake_search(corpus, query, top_k=8, pipeline=None):
        seen.update(corpus=corpus, query=query, top_k=top_k, pipeline=pipeline)
        return {"hits": [{"citation": "a.pdf p.1"}]}

    monkeypatch.setattr(server.core, "search", fake_search)
    out = server.dispatch("search", {"corpus": "verify", "query": "terms", "top_k": 3})
    assert out == {"hits": [{"citation": "a.pdf p.1"}]}
    assert seen == {"corpus": "verify", "query": "terms", "top_k": 3, "pipeline": None}


def test_dispatch_search_doc_routes_to_core(monkeypatch):
    seen = {}

    def fake_search_document(document_id, query, top_k=8, pipeline=None):
        seen.update(document_id=document_id, query=query, top_k=top_k, pipeline=pipeline)
        return {"hits": [{"citation": "a.pdf p.1"}]}

    monkeypatch.setattr(server.core, "search_document", fake_search_document)
    out = server.dispatch("search-doc", {"document_id": 5, "query": "terms", "top_k": 3})
    assert out == {"hits": [{"citation": "a.pdf p.1"}]}
    assert seen == {"document_id": 5, "query": "terms", "top_k": 3, "pipeline": None}


def test_dispatch_get_doc_routes_to_core(monkeypatch):
    seen = {}

    def fake_get_doc(document_id, pipeline=None):
        seen.update(document_id=document_id, pipeline=pipeline)
        return {"document_id": document_id, "text": "x"}

    monkeypatch.setattr(server.core, "get_doc", fake_get_doc)
    out = server.dispatch("get-doc", {"document_id": 5, "pipeline": "p_docling"})
    assert out["document_id"] == 5
    assert seen == {"document_id": 5, "pipeline": "p_docling"}


def test_dispatch_list_pipelines_routes_to_core(monkeypatch):
    seen = {}

    def fake_list_pipelines(corpus=None, document_id=None):
        seen.update(corpus=corpus, document_id=document_id)
        return {"document_id": document_id, "pipelines": []}

    monkeypatch.setattr(server.core, "list_pipelines", fake_list_pipelines)
    out = server.dispatch("list-pipelines", {"document_id": 5})
    assert out == {"document_id": 5, "pipelines": []}
    assert seen == {"corpus": None, "document_id": 5}


def test_dispatch_list_corpora_and_documents(monkeypatch):
    monkeypatch.setattr(server.core, "list_corpora", lambda: {"corpora": []})
    monkeypatch.setattr(server.core, "list_documents",
                        lambda corpus: {"corpus": corpus, "documents": []})
    assert server.dispatch("list-corpora", {}) == {"corpora": []}
    assert server.dispatch("list-documents", {"corpus": "verify"})["corpus"] == "verify"


def test_dispatch_unknown_tool_raises_value_error():
    with pytest.raises(ValueError):
        server.dispatch("nope", {})


def test_dispatch_propagates_cli_error(monkeypatch):
    def boom():
        raise http.CliError("could not reach http://localhost:8000; is the stack up?")

    monkeypatch.setattr(server.core, "list_corpora", boom)
    with pytest.raises(http.CliError):
        server.dispatch("list-corpora", {})
