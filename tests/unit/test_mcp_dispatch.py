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


def test_dispatch_list_goals_routes_to_core(monkeypatch):
    monkeypatch.setattr(server.core, "alchemy_list_goals",
                        lambda: [{"id": 1, "name": "find_vuln", "corpus_id": 3}])
    out = server.dispatch("list-goals", {})
    # wrapped: MCP structured content must be a dict; core returns a bare list
    assert out == {"goals": [{"id": 1, "name": "find_vuln", "corpus_id": 3}]}


def test_dispatch_goal_runs_routes_to_core(monkeypatch):
    seen = {}

    def fake_list_runs(ref):
        seen["ref"] = ref
        return [{"version": 2, "status": "running"}]

    monkeypatch.setattr(server.core, "alchemy_list_runs", fake_list_runs)
    out = server.dispatch("goal-runs", {"goal": "find_vuln"})
    assert out == {"runs": [{"version": 2, "status": "running"}]}
    assert seen == {"ref": "find_vuln"}


def test_dispatch_export_goal_run_routes_to_core(monkeypatch):
    seen = {}

    def fake_export(ref, version=None):
        seen.update(ref=ref, version=version)
        return {"goal": ref, "version": 2, "status": "done",
                "draft_markdown": "# D", "sections": [], "citations": 0}

    monkeypatch.setattr(server.core, "alchemy_export_run", fake_export)
    out = server.dispatch("export-goal-run", {"goal": "find_vuln"})
    assert out["version"] == 2
    assert seen == {"ref": "find_vuln", "version": None}   # omitted -> latest


def test_dispatch_run_goal_routes_to_core(monkeypatch):
    seen = {}

    def fake_run(ref, provider, model, *, coverage=None, guidance=None,
                 based_on_version=None, budget_chars=100_000, max_rounds=8,
                 max_llm_calls=None, fresh_coverage=False):
        seen.update(ref=ref, provider=provider, model=model, coverage=coverage,
                    guidance=guidance, max_llm_calls=max_llm_calls)
        return {"version": 3, "status": "pending"}

    monkeypatch.setattr(server.core, "alchemy_run", fake_run)
    out = server.dispatch("run-goal", {"goal": "find_vuln", "max_llm_calls": 6,
                                       "guidance": "dig", "coverage": "full"})
    assert out == {"version": 3, "status": "pending"}
    # provider/model omitted -> None passes through (server-side fallback)
    assert seen == {"ref": "find_vuln", "provider": None, "model": None,
                    "coverage": "full", "guidance": "dig", "max_llm_calls": 6}
