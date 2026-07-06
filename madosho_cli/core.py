"""Pure orchestration core for the madosho agent-tools.

The agent tools (search, search-doc, get-doc, list-corpora, list-documents,
list-pipelines) as plain functions that take args and RETURN dicts - no argv, no
printing. Both the CLI
(commands.py wraps these for stdout/--json) and the OpenAPI tool server
(madosho_toolserver) call these, so every retrieval door shares one behavior and
cannot drift. HTTP transport lives in http.py; the agent-tools manifest
(manifest.py) is the single source of truth for each function's parameter schema.
Stays a pure HTTP client - no kernel/server imports.
"""
from __future__ import annotations

import json
import time
from typing import Any

from . import http


def create_corpus(name: str) -> dict[str, Any]:
    return http.post_json(f"{http.control_base()}/corpora", {"name": name})


def upload_document(
    path: str | None = None,
    content_b64: str | None = None,
    filename: str | None = None,
    corpus: str | None = None,
    parser: str | None = None,
    chunker: str | None = None,
    embedder: str | None = None,
    options: Any = None,
) -> dict[str, Any]:
    if not (bool(path) ^ bool(content_b64)):
        raise http.CliError("exactly one of 'path' or 'content_b64' must be given")
    if path:
        fields = {
            k: v for k, v in {
                "parser": parser,
                "chunker": chunker,
                "embedder": embedder,
                "name": filename,
                "options": json.dumps(options) if isinstance(options, dict) else options,
            }.items() if v is not None
        }
        if corpus:
            cid = _resolve_corpus_id(corpus)
            url = f"{http.control_base()}/corpora/{cid}/documents"
        else:
            url = f"{http.control_base()}/documents"
        return http.post_multipart(url, fields, path)
    else:
        payload = {
            k: v for k, v in {
                "content_b64": content_b64,
                "filename": filename,
                "corpus": corpus,
                "parser": parser,
                "chunker": chunker,
                "embedder": embedder,
                "options": options,
            }.items() if v is not None
        }
        return http.post_json(f"{http.control_base()}/documents/ingest", payload)


def build_pipeline(
    document_id: int,
    name: str,
    parser: str | None = None,
    chunker: str | None = None,
    embedder: str | None = None,
    options: Any = None,
    config: dict | None = None,
) -> dict[str, Any]:
    payload = {
        k: v for k, v in {
            "name": name,
            "parser": parser,
            "chunker": chunker,
            "embedder": embedder,
            "options": options,
            "config": config,
        }.items() if v is not None
    }
    return http.post_json(
        f"{http.control_base()}/documents/{document_id}/pipelines", payload
    )


def add_document_to_corpus(corpus: str, document_id: int) -> dict[str, Any]:
    cid = _resolve_corpus_id(corpus)
    return http.post_json(
        f"{http.control_base()}/corpora/{cid}/documents/{document_id}", {}
    )


def document_status(document_id: int) -> dict[str, Any]:
    doc = http.get_json(f"{http.control_base()}/documents/{document_id}")
    pipelines = http.get_json(
        f"{http.control_base()}/documents/{document_id}/pipelines"
    )
    return {
        "id": doc["id"],
        "status": doc["status"],
        "error": doc.get("error"),
        "progress": doc.get("progress"),
        "pipelines": pipelines,
    }


def list_corpora() -> dict[str, Any]:
    rows = http.get_json(f"{http.control_base()}/corpora")
    return {"corpora": [{"id": c["id"], "name": c["name"]} for c in rows]}


def _resolve_corpus_id(name: str) -> int:
    rows = http.get_json(f"{http.control_base()}/corpora")
    for c in rows:
        if c["name"] == name:
            return c["id"]
    raise http.CliError(f"corpus not found: {name!r}")


def list_documents(corpus: str) -> dict[str, Any]:
    corpus_id = _resolve_corpus_id(corpus)
    rows = http.get_json(f"{http.control_base()}/corpora/{corpus_id}/documents")
    docs = [
        {
            "id": d["id"],
            "filename": d["filename"],
            "status": d["status"],
            "selected_pipeline_id": d.get("selected_pipeline_id"),
        }
        for d in rows
    ]
    return {"corpus": corpus, "documents": docs}


def _run_query(payload: dict[str, Any], top_k: int) -> dict[str, Any]:
    """POST a retrieval-only /query body and return the top_k hits. Shared by the
    corpus-scoped (search) and document-scoped (search_document) paths so both
    behave identically apart from the scope key in the payload."""
    result = http.post_json(f"{http.query_base()}/query", payload)
    return {"hits": result.get("hits", [])[:top_k]}


def search(corpus: str, query: str, top_k: int = 8,
           pipeline: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"corpus": corpus, "prompt": query}
    if pipeline:
        payload["pipelines"] = [pipeline]
    return _run_query(payload, top_k)


def search_document(document_id: int, query: str, top_k: int = 8,
                    pipeline: str | None = None) -> dict[str, Any]:
    # RAG over a single document. The query plane accepts document_id in place of
    # corpus (exactly one of the two), so the only difference from search() is the
    # scope key - same ranked, cited hits come back.
    payload: dict[str, Any] = {"document_id": document_id, "prompt": query}
    if pipeline:
        payload["pipelines"] = [pipeline]
    return _run_query(payload, top_k)


def list_pipelines(corpus: str | None = None,
                   document_id: int | None = None) -> dict[str, Any]:
    """Enumerate the named pipelines on one document or across a corpus, so an
    agent can discover names to pass via --pipeline. Exactly one scope is required."""
    if (corpus is None) == (document_id is None):
        raise http.CliError("exactly one of 'corpus' or 'document_id' is required")
    if document_id is not None:
        # Control plane: this document's pipelines carry the pipeline id.
        rows = http.get_json(
            f"{http.control_base()}/documents/{document_id}/pipelines")
        pls = [
            {"id": p["id"], "name": p["name"], "rating": p.get("rating"),
             "status": p["status"], "effective": p.get("effective", False)}
            for p in rows
        ]
        return {"document_id": document_id, "pipelines": pls}
    # Query plane: a corpus's pipelines are flattened across member documents
    # (carries document_id, not the pipeline id).
    rows = http.get_json(f"{http.query_base()}/corpora/{corpus}/pipelines")
    pls = [
        {"name": p["name"], "document_id": p["document_id"], "rating": p.get("rating"),
         "status": p["status"], "effective": p.get("effective", False)}
        for p in rows
    ]
    return {"corpus": corpus, "pipelines": pls}


def _resolve_pipeline(document_id: int, name: str | None) -> dict:
    rows = http.get_json(f"{http.control_base()}/documents/{document_id}/pipelines")
    if not rows:
        raise http.CliError(f"document {document_id} has no pipelines")
    if name is not None:
        for p in rows:
            if p["name"] == name:
                return p
        raise http.CliError(
            f"document {document_id} has no pipeline named {name!r}")
    for p in rows:
        if p.get("effective"):
            return p
    raise http.CliError(
        f"document {document_id} has no effective pipeline (none indexed yet)")


def get_doc(document_id: int, pipeline: str | None = None) -> dict[str, Any]:
    pl = _resolve_pipeline(document_id, pipeline)
    arts = http.get_json(f"{http.control_base()}/pipelines/{pl['id']}/artifacts")
    chunks = sorted(arts.get("chunks", []), key=lambda c: c.get("position", 0))
    text = "\n\n".join(c.get("text", "") for c in chunks)
    return {
        "document_id": document_id,
        "pipeline": pl["name"],
        "pipeline_id": pl["id"],
        "char_count": len(text),
        "text": text,
    }


_ACTIVE_STATUSES = {"pending", "running"}

# Maps the user-facing --type value to the URL path segment used by the API.
# research -> /corpora/{id}/research and /research/{id}/cancel
# eval     -> /corpora/{id}/evals    and /evals/{id}/cancel
_TYPE_PATH = {"research": "research", "eval": "evals"}


def list_runs(corpus_id: int, run_type: str, active_only: bool = False) -> dict[str, Any]:
    """GET the research or eval runs for a corpus, optionally filtered to active only."""
    path = _TYPE_PATH[run_type]
    rows = http.get_json(f"{http.control_base()}/corpora/{corpus_id}/{path}")
    if active_only:
        rows = [r for r in rows if r.get("status") in _ACTIVE_STATUSES]
    return {"runs": rows}


def cancel_run(run_id: int, run_type: str) -> dict[str, Any]:
    """POST to the cancel endpoint for a research or eval run."""
    path = _TYPE_PATH[run_type]
    return http.post_json(f"{http.control_base()}/{path}/{run_id}/cancel", {})


_TERMINAL = {"indexed", "failed"}


def wait_for_document(
    document_id: int,
    *,
    on_event=None,
    interval: float = 2.0,
    timeout: float = 900.0,
) -> dict[str, Any]:
    """Poll document_status until status reaches a terminal state.

    Loop order per poll: fetch -> on_event -> terminal check -> timeout check -> sleep.
    The terminal poll fires on_event before returning so callers see every transition.
    Raises CliError if timeout is exceeded before a terminal status is reached.
    """
    start = time.monotonic()
    while True:
        status = document_status(document_id)
        if on_event is not None:
            on_event(status)
        if status["status"] in _TERMINAL:
            return status
        if time.monotonic() - start >= timeout:
            raise http.CliError(
                f"timed out after {timeout}s waiting for document {document_id}"
            )
        time.sleep(interval)


def alchemy_create(name: str, corpus: str, spec: dict[str, Any],
                   goal_type: str = "living-research",
                   coverage: str = "search") -> dict[str, Any]:
    payload = {"name": name, "corpus_id": _resolve_corpus_id(corpus),
               "goal_type": goal_type, "spec": spec, "coverage": coverage}
    return http.post_json(f"{http.control_base()}/alchemy/goals", payload)


def alchemy_run(ref: str, provider: str, model: str, *, coverage: str | None = None,
                guidance: str | None = None, based_on_version: int | None = None,
                budget_chars: int = 100_000, max_rounds: int = 8,
                max_llm_calls: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"llm": {"provider": provider, "model": model},
                               "budget_chars": budget_chars, "max_rounds": max_rounds}
    if coverage:
        payload["coverage"] = coverage
    if guidance:
        payload["guidance"] = guidance
    if based_on_version is not None:
        payload["based_on_version"] = based_on_version
    if max_llm_calls is not None:
        payload["max_llm_calls"] = max_llm_calls
    return http.post_json(
        f"{http.control_base()}/alchemy/goals/{ref}/runs", payload)


def alchemy_list_goals() -> list[dict[str, Any]]:
    return http.get_json(f"{http.control_base()}/alchemy/goals")


def alchemy_list_runs(ref: str) -> list[dict[str, Any]]:
    return http.get_json(f"{http.control_base()}/alchemy/goals/{ref}/runs")


def alchemy_get_run(ref: str, version: int) -> dict[str, Any]:
    return http.get_json(
        f"{http.control_base()}/alchemy/goals/{ref}/runs/{version}")


def alchemy_finalize(ref: str, version: int) -> dict[str, Any]:
    return http.post_json(
        f"{http.control_base()}/alchemy/goals/{ref}/finalize",
        {"version": version})


def alchemy_cancel(run_id: int) -> dict[str, Any]:
    return http.post_json(f"{http.control_base()}/alchemy/runs/{run_id}/cancel", {})


def alchemy_latest_version(ref: str) -> int | None:
    """Version number of a goal's newest run, or None if it has none."""
    runs = alchemy_list_runs(ref)
    return runs[0]["version"] if runs else None


_ALCHEMY_TERMINAL = {"done", "failed", "cancelled"}


def wait_for_alchemy_run(ref: str, version: int, *, on_event, interval: float = 3.0,
                         timeout: float = 1800.0) -> dict[str, Any]:
    """Poll a run until it reaches a terminal status (mirrors wait_for_pipeline).

    on_event receives the full run dict each poll (same contract as
    wait_for_document/wait_for_pipeline, so _on_event_printer works unchanged -
    it reads "status" and "progress" off the top-level dict).
    Raises CliError on timeout.
    """
    start = time.monotonic()
    while True:
        run = alchemy_get_run(ref, version)
        on_event(run)
        if run.get("status") in _ALCHEMY_TERMINAL:
            return run
        if time.monotonic() - start >= timeout:
            raise http.CliError(f"timed out waiting for run {ref} v{version}")
        time.sleep(interval)


def wait_for_pipeline(
    document_id: int,
    pipeline_id: int,
    *,
    on_event=None,
    interval: float = 2.0,
    timeout: float = 900.0,
) -> dict[str, Any]:
    """Poll document_status until the named pipeline reaches a terminal state.

    If the target pipeline is not yet present in the response, the poll is
    treated as non-terminal. Same loop order as wait_for_document.
    Raises CliError on timeout.
    """
    start = time.monotonic()
    while True:
        status = document_status(document_id)
        if on_event is not None:
            on_event(status)
        for pl in status.get("pipelines", []):
            if pl["id"] == pipeline_id and pl["status"] in _TERMINAL:
                return status
        if time.monotonic() - start >= timeout:
            raise http.CliError(
                f"timed out after {timeout}s waiting for pipeline {pipeline_id} "
                f"on document {document_id}"
            )
        time.sleep(interval)
