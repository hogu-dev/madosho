"""madosho OpenAPI tool server - retrieval as registerable tools.

Re-publishes the agent-tools manifest (madosho_cli.manifest) as an OpenAPI 3.x
spec a chat frontend (Open WebUI) registers under Admin Settings > Tools. Each
manifest tool becomes one POST endpoint whose operation_id IS the tool name and
whose request body is the tool's `parameters` schema. Handlers delegate to the
shared CLI orchestration core (madosho_cli.core), so the CLI, this tool server,
and the future MCP server have one behavior and cannot drift (a guard test,
test_toolserver_contract.py, fails if the request schemas drift from the
manifest). Pure HTTP client - imports nothing from the kernel or madosho_server,
exactly like madosho-cli.
"""
from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRouter
from pydantic import BaseModel, Field

from madosho_cli import core, http

app = FastAPI(
    title="madosho-toolserver",
    version="1",
    description="madosho retrieval tools as an OpenAPI tool server (retrieval only). "
                "Register this server's URL in Open WebUI under Settings > Tools.",
)

# A browser-based chat frontend (e.g. Open WebUI's "Manage Tool Servers") fetches
# /openapi.json client-side and cross-origin (e.g. :3000 -> :8088). Without CORS
# headers the browser blocks the response and registration fails with a vague
# "failed to connect". The permissive, credential-free policy here is intentional:
# auth is now enforced UPSTREAM (the forwarded Bearer carries the caller's key to
# the madosho control/query plane); the toolserver itself holds no key. Browsers
# need CORS to fetch /openapi.json for anonymous tool registration; the actual tool
# calls carry the caller's key in the Authorization header which is forwarded.
# Backend-side clients (the Python demo, the CLI, the MCP server) don't need this
# -- only browsers enforce CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _guard(fn, *args):
    """Run a CLI-core call and relay errors faithfully to the caller.

    Upstream 4xx (400-499) are relayed with the exact same status code.  These
    are CLIENT errors -- the caller's key scope, request body, or target resource
    is what's wrong, not the gateway.  Collapsing a 403 scope-denial into a 502
    is actively misleading: it tells the caller "bad gateway" when the real
    message is "your key is read-only."

    5xx and connection failures (CliError.status is None or >= 500) are mapped to
    502 because those ARE upstream/gateway problems; the toolserver has no better
    information to give the caller than "upstream is down or broken."

    WHY NOT string-parse the message: CliError.status is a typed int set at raise
    time; parsing "HTTP 403 from ..." would be fragile and break on any message
    text change.
    """
    try:
        return fn(*args)
    except http.CliError as e:
        upstream = e.status
        if upstream is not None and 400 <= upstream <= 499:
            # Relay the upstream client-error verdict unchanged.  The caller's
            # key/scope/request is wrong, not the gateway -- the caller deserves
            # the real code (401 = no auth, 403 = scope denied, 404 = not found,
            # 422 = bad payload).
            raise HTTPException(status_code=upstream, detail=str(e))
        # None (connection failure / unreachable host) or 5xx (upstream server
        # error) -> 502 Bad Gateway is the correct proxy response.
        raise HTTPException(status_code=502, detail=str(e))


async def _inject_bearer(request: Request):
    """Forward the caller's bearer token to every upstream call this request makes.

    Why an async yield-dependency rather than middleware:
    Starlette BaseHTTPMiddleware does NOT reliably propagate contextvar values
    to the endpoint handler because the downstream app runs in a separate asyncio
    task. An async FastAPI dependency runs in the REQUEST's own task context;
    when FastAPI then calls the sync handler via anyio.to_thread.run_sync, anyio
    copies THAT context (including the contextvar set here) into the worker thread.
    Each concurrent request is its own asyncio task with its own context copy, so
    there is zero bleed between concurrent callers.

    Only the raw token (without the "Bearer " prefix) is passed to
    http.set_request_token(); _auth_headers() then reconstructs the full header.
    If no Bearer scheme is present the contextvar is set to None and _auth_headers()
    falls back to the process-wide MADOSHO_API_KEY env var (unchanged CLI behavior).
    """
    auth = request.headers.get("Authorization", "")
    token: str | None = None
    if auth.lower().startswith("bearer "):
        token = auth[7:]   # strip the 7-char "Bearer " prefix
    tok = http.set_request_token(token)
    try:
        yield
    finally:
        http.reset_request_token(tok)


# All tool POST routes are grouped under this router so the inject-bearer
# dependency is declared once. /health and /openapi.json are NOT in this router
# so they stay open for anonymous Open WebUI registration.
_tools = APIRouter(dependencies=[Depends(_inject_bearer)])


# Request models mirror madosho_cli/manifest.py. The contract guard test keeps
# them honest: operationId == tool name, and these properties/required match the
# manifest `parameters` exactly.
class SearchBody(BaseModel):
    corpus: str = Field(..., description="corpus name to search")
    query: str = Field(..., description="the search query text")
    top_k: int = Field(8, description="max number of chunks to return (default 8)")
    pipeline: str | None = Field(
        None, description="optional pipeline name to retrieve through (overrides "
                          "each document's effective pipeline)")


class SearchDocBody(BaseModel):
    document_id: int = Field(
        ..., description="the document id (from list-documents) to search within")
    query: str = Field(..., description="the search query text")
    top_k: int = Field(8, description="max number of chunks to return (default 8)")
    pipeline: str | None = Field(
        None, description="optional pipeline name to retrieve through (defaults to "
                          "the document's effective pipeline)")


class GetDocBody(BaseModel):
    document_id: int = Field(..., description="the document id (from list-documents)")
    pipeline: str | None = Field(
        None, description="optional pipeline name; defaults to the document's "
                          "effective pipeline")


class ListCorporaBody(BaseModel):
    pass


class ListDocumentsBody(BaseModel):
    corpus: str = Field(..., description="corpus name")


class ListPipelinesBody(BaseModel):
    corpus: str | None = Field(
        None, description="list pipelines across this corpus's documents")
    document_id: int | None = Field(
        None, description="list pipelines built on this one document")


class CreateCorpusBody(BaseModel):
    name: str = Field(..., description="corpus name to create")


class UploadDocumentBody(BaseModel):
    path: str | None = Field(None, description="local file path to upload")
    content_b64: str | None = Field(
        None, description="base-64 encoded document bytes (alternative to path)")
    filename: str | None = Field(
        None, description="display filename (required when using content_b64)")
    corpus: str | None = Field(None, description="assign to this corpus by name on upload")
    parser: str | None = Field(None, description="parser component override")
    chunker: str | None = Field(None, description="chunker component override")
    embedder: str | None = Field(None, description="embedder component override")
    options: dict[str, Any] | None = Field(None, description="additional pipeline component options")


class BuildPipelineBody(BaseModel):
    document_id: int = Field(..., description="document id to build the pipeline for")
    name: str = Field(..., description="pipeline name (must be unique within the document)")
    parser: str | None = Field(None, description="parser component override")
    chunker: str | None = Field(None, description="chunker component override")
    embedder: str | None = Field(None, description="embedder component override")
    options: dict[str, Any] | None = Field(None, description="additional component options")
    config: dict[str, Any] | None = Field(
        None, description="raw pipeline config dict (overrides component-level args)")


class AddDocumentToCorpusBody(BaseModel):
    corpus: str = Field(..., description="corpus name to add the document to")
    document_id: int = Field(..., description="id of the document to add")


class DocumentStatusBody(BaseModel):
    document_id: int = Field(..., description="document id to check")


class ListGoalsBody(BaseModel):
    pass


class GoalRunsBody(BaseModel):
    goal: str = Field(..., description="goal name or id")


class ExportGoalRunBody(BaseModel):
    goal: str = Field(..., description="goal name or id")
    version: int | None = Field(
        None, description="run version to export (default: the latest run)")


class RunGoalBody(BaseModel):
    goal: str = Field(..., description="goal name or id")
    max_llm_calls: int = Field(
        ..., description="hard cap on LLM calls for this run (required)")
    guidance: str | None = Field(
        None, description="optional steering note for this run")
    coverage: str | None = Field(
        None, description="coverage mode override: search, full, or exhaustive")
    provider: str | None = Field(
        None, description="LLM provider (default: the server's default llm endpoint)")
    model: str | None = Field(
        None, description="LLM model name (default: the server's default llm endpoint)")
    reasoning_effort: str | None = Field(
        None, description="model-native reasoning effort (e.g. low, high); "
                          "omit to use the endpoint's default")


class ListKbsBody(BaseModel):
    pass


class GetKbPageBody(BaseModel):
    kb_id: int = Field(..., description="the KB id (from list-kbs)")
    slug: str = Field(..., description="the page slug (from search-kb)")


class SearchKbBody(BaseModel):
    kb_id: int = Field(..., description="the KB id (from list-kbs)")
    query: str = Field(..., description="search text")


@app.get("/health")
def health():
    return {"status": "ok"}


@_tools.post("/search", operation_id="search",
             summary="RAG retrieval: search a corpus and return ranked, cited chunks.")
def search(body: SearchBody):
    return _guard(core.search, body.corpus, body.query, body.top_k, body.pipeline)


@_tools.post("/search-doc", operation_id="search-doc",
             summary="RAG retrieval scoped to one document; ranked, cited chunks.")
def search_doc(body: SearchDocBody):
    return _guard(core.search_document, body.document_id, body.query,
                  body.top_k, body.pipeline)


@_tools.post("/get-doc", operation_id="get-doc",
             summary="Return the full extracted text of one document (no RAG).")
def get_doc(body: GetDocBody):
    return _guard(core.get_doc, body.document_id, body.pipeline)


@_tools.post("/list-corpora", operation_id="list-corpora",
             summary="List the corpora available to search.")
def list_corpora(body: ListCorporaBody):
    return _guard(core.list_corpora)


@_tools.post("/list-documents", operation_id="list-documents",
             summary="List the documents in a corpus (id, filename, status).")
def list_documents(body: ListDocumentsBody):
    return _guard(core.list_documents, body.corpus)


@_tools.post("/list-pipelines", operation_id="list-pipelines",
             summary="List pipelines on a document or across a corpus, with ratings.")
def list_pipelines(body: ListPipelinesBody):
    return _guard(core.list_pipelines, body.corpus, body.document_id)


@_tools.post("/create-corpus", operation_id="create-corpus",
             summary="Create a new corpus (document collection) by name.")
def create_corpus(body: CreateCorpusBody):
    return _guard(core.create_corpus, body.name)


@_tools.post("/upload-document", operation_id="upload-document",
             summary="Upload a document (local file path or base-64 bytes).")
def upload_document(body: UploadDocumentBody):
    return _guard(lambda: core.upload_document(
        path=body.path,
        content_b64=body.content_b64,
        filename=body.filename,
        corpus=body.corpus,
        parser=body.parser,
        chunker=body.chunker,
        embedder=body.embedder,
        options=body.options,
    ))


@_tools.post("/build-pipeline", operation_id="build-pipeline",
             summary="Build a named extraction/retrieval pipeline for a document.")
def build_pipeline(body: BuildPipelineBody):
    return _guard(lambda: core.build_pipeline(
        body.document_id,
        body.name,
        parser=body.parser,
        chunker=body.chunker,
        embedder=body.embedder,
        options=body.options,
        config=body.config,
    ))


@_tools.post("/add-document-to-corpus", operation_id="add-document-to-corpus",
             summary="Add an existing document to a corpus by name.")
def add_document_to_corpus(body: AddDocumentToCorpusBody):
    return _guard(core.add_document_to_corpus, body.corpus, body.document_id)


@_tools.post("/document-status", operation_id="document-status",
             summary="Return the current status and pipeline list for a document.")
def document_status(body: DocumentStatusBody):
    return _guard(core.document_status, body.document_id)


@_tools.post("/list-goals", operation_id="list-goals",
             summary="List the alchemy goals (autonomous research/report objectives).")
def list_goals(body: ListGoalsBody):
    return _guard(core.alchemy_list_goals)


@_tools.post("/goal-runs", operation_id="goal-runs",
             summary="List an alchemy goal's runs, newest first.")
def goal_runs(body: GoalRunsBody):
    return _guard(core.alchemy_list_runs, body.goal)


@_tools.post("/export-goal-run", operation_id="export-goal-run",
             summary="Return one alchemy run's draft markdown + slim section summary.")
def export_goal_run(body: ExportGoalRunBody):
    return _guard(lambda: core.alchemy_export_run(body.goal, version=body.version))


@_tools.post("/run-goal", operation_id="run-goal",
             summary="Start a new run of an alchemy goal (returns immediately; "
                     "poll goal-runs).")
def run_goal(body: RunGoalBody):
    return _guard(lambda: core.alchemy_run(
        body.goal, body.provider, body.model,
        coverage=body.coverage,
        guidance=body.guidance,
        max_llm_calls=body.max_llm_calls,
        reasoning_effort=body.reasoning_effort,
    ))


@_tools.post("/list-kbs", operation_id="list-kbs",
             summary="List the server-owned knowledge bases (id, name, corpus).")
def list_kbs(body: ListKbsBody):
    return _guard(core.list_kbs)


@_tools.post("/get-kb-page", operation_id="get-kb-page",
             summary="Return one knowledge-base page in full (frontmatter + body) "
                     "by its slug.")
def get_kb_page(body: GetKbPageBody):
    return _guard(core.get_kb_page, body.kb_id, body.slug)


@_tools.post("/search-kb", operation_id="search-kb",
             summary="Full-text search over one KB's pages; returns matching page "
                     "summaries.")
def search_kb(body: SearchKbBody):
    return _guard(core.search_kb, body.kb_id, body.query)


app.include_router(_tools)


def run() -> None:
    """`madosho-toolserver`: serve the OpenAPI tool server (retrieval only)."""
    import uvicorn
    uvicorn.run("madosho_toolserver.app:app", host="0.0.0.0", port=8088)
