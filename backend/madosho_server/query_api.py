from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from madosho.core.errors import MadoshoError
from madosho_server import db, kb_index, kb_store, llm, membership, pipeline_cache, pipelines as pipelines_mod, query_core, retrieval
from madosho_server.auth import make_auth_dependency
from madosho_server.llm_endpoints import endpoint_creds, endpoint_reasoning_effort
from madosho_server.settings import Settings

logger = logging.getLogger(__name__)


def get_settings() -> Settings:
    return Settings.from_env()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    db.configure_engine(settings.database_url)
    db.create_all()                 # idempotent; init_db also does this in compose
    db.seed_llm_endpoints_from_env(settings)
    yield
    if db.engine is not None:
        db.engine.dispose()


# Query plane: every route is a read (even POST /query and /v1/chat/completions only
# retrieve), so any valid key suffices.
query_auth = make_auth_dependency(lambda req: "read")
app = FastAPI(title="madosho-query", lifespan=lifespan, dependencies=[Depends(query_auth)])

SessionDep = Annotated[Session, Depends(db.get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _corpus_row_or_404(session: Session, name: str) -> db.Corpus:
    row = session.scalar(select(db.Corpus).where(db.Corpus.name == name))
    if row is None:
        raise HTTPException(status_code=404, detail="corpus not found")
    return row


def _open_pipeline(settings: Settings):
    return lambda p: pipeline_cache.corpus_for(p, settings.corpora_dir)


def _resolve_answer_llm(session, settings, body_llm: str):
    """Resolve the Answer LLM to (provider, model, settings, reasoning_effort).
    `body_llm` is a registry endpoint NAME first (binds that endpoint's OWN
    api_base/key onto a Settings copy, and carries its reasoning_effort default);
    else the legacy 'provider:model' on global settings (effort looked up by
    provider/model). Returns None when body_llm resolves to neither."""
    row = session.scalar(select(db.LlmEndpoint).where(db.LlmEndpoint.name == body_llm))
    if row is not None:
        creds = endpoint_creds(settings, row)
        return row.provider, row.model, creds, row.reasoning_effort
    provider, _, model = body_llm.partition(":")
    if provider and model:
        return (provider, model, settings,
                endpoint_reasoning_effort(session, provider, model))
    return None


class QueryRequest(BaseModel):
    corpus: str | None = None
    document_id: int | None = None
    prompt: str
    llm: str | None = None          # "provider:model"
    pipelines: list[str] | None = None
    include_generated: bool = True  # False hides alchemy-generated docs (work-unit exclusion)


class Citation(BaseModel):
    """One retrieved, attributed chunk in a /query response. `source` is the
    basename'd document label (full path lives in the kernel for provenance);
    document_id is the real linkage key. pipeline_id/pipeline carry the D14
    pipeline attribution. The retriever-only path (serialize_hits) omits the
    pipeline fields, so they are optional."""
    text: str
    score: float
    page: int | None = None
    citation: str
    source: str | None = None
    document_id: int | None = None
    position: int | None = None
    pipeline_id: int | None = None
    pipeline: str | None = None
    origin: str | None = None    # provenance: "source" | "generated" (D-stage)


class QueryHitsResponse(BaseModel):
    """Retrieval-only response (no `llm` in the request). madosho never calls a model."""
    hits: list[Citation]


class QueryAnswerResponse(BaseModel):
    """Proxy response: madosho generated an answer. `messages` is the exact augmented
    prompt the model saw (system + user), so the Playground can show it."""
    answer: str
    citations: list[Citation]
    usage: dict | None = None
    messages: list[dict]


class HealthResponse(BaseModel):
    status: str


class ModelCard(BaseModel):
    id: str
    object: str
    created: int
    owned_by: str


class ModelsResponse(BaseModel):
    object: str
    data: list[ModelCard]


class PipelineCard(BaseModel):
    """A built pipeline on one of a corpus's documents (query-plane list)."""
    name: str
    document_id: int
    slots: dict
    rating: float | None = None
    status: str
    effective: bool


class ErrorResponse(BaseModel):
    """Native/control-plane error envelope (FastAPI default): a single human string."""
    detail: str


class OpenAIErrorBody(BaseModel):
    message: str
    type: str
    code: str | None = None


class OpenAIErrorResponse(BaseModel):
    """OpenAI-shaped error envelope the shim returns.
    Kept distinct from ErrorResponse on purpose — real OpenAI clients depend on it."""
    error: OpenAIErrorBody


@app.get("/health", response_model=HealthResponse)
def health():
    return {"status": "ok"}


class KbPageSummary(BaseModel):
    slug: str
    type: str
    title: str
    description: str


@app.get("/kbs/{kb_id}/search", response_model=list[KbPageSummary],
         responses={404: {"model": ErrorResponse}})
def kb_search(kb_id: int, session: SessionDep, settings: SettingsDep,
              q: str = Query(..., min_length=1)):
    """Fused KB retrieval: RRF-merge the lexical page scan with page-level
    semantic search over the KB's vector collection. Runs on the query plane
    because it owns the embedder. Degrades to lexical-only when the KB has no
    vector collection yet (never indexed) or the vector lane is unavailable."""
    kb = session.get(db.Kb, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="knowledge base not found")
    root = kb_store.kb_root(settings.kb_dir, kb.id)
    lexical = kb_store.search_pages(root, q)
    semantic: list = []
    try:
        store = kb_index.open_store(settings.qdrant_url, kb.id)
        if store.native.collection_exists(kb_index.kb_collection(kb.id)):
            semantic = kb_index.search(store, kb_index.get_embedder(), q)
    except Exception:
        logger.warning("kb_search: semantic lane unavailable for kb %s; "
                       "returning lexical only", kb.id, exc_info=True)
    return kb_index.fuse(lexical, semantic)


@app.post("/query", response_model=QueryAnswerResponse | QueryHitsResponse,
          responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse},
                     422: {"model": ErrorResponse}})
def query(body: QueryRequest, session: SessionDep, settings: SettingsDep):
    if (body.corpus is None) == (body.document_id is None):
        raise HTTPException(status_code=422,
                            detail="exactly one of 'corpus' or 'document_id' is required")
    try:
        if body.document_id is not None:
            doc = session.get(db.Document, body.document_id)
            if doc is None:
                raise HTTPException(status_code=404, detail="document not found")
            ph = retrieval.single_document_query(
                session, doc, body.prompt, open_pipeline=_open_pipeline(settings),
                pipeline_names=body.pipelines)
        else:
            row = _corpus_row_or_404(session, body.corpus)
            ph = retrieval.multi_pipeline_query(
                session, row, body.prompt, open_pipeline=_open_pipeline(settings),
                pipeline_names=body.pipelines,
                include_generated=body.include_generated)
    except MadoshoError as e:
        raise HTTPException(status_code=400, detail=str(e))
    hits = [p.hit for p in ph]   # bare Hit list for generation; ph kept for pipeline-attributed citations
    # Provenance labels: ONE lookup over the distinct hit documents (not one per
    # hit) mapping document_id -> (origin, origin_meta), so a generated doc's
    # chunks render "[generated: <goal> v<n>]" in their citation.
    doc_ids = {p.document_id for p in ph}
    origins: dict[int, tuple[str, dict]] = {}
    if doc_ids:
        rows = session.execute(
            select(db.Document.id, db.Document.origin, db.Document.origin_meta)
            .where(db.Document.id.in_(doc_ids))).all()
        origins = {i: (o, m or {}) for i, o, m in rows}

    if not body.llm:
        return {"hits": query_core.serialize_pipeline_hits(ph, origins=origins)}

    resolved = _resolve_answer_llm(session, settings, body.llm)
    if resolved is None:
        raise HTTPException(status_code=422, detail="llm must be an endpoint name or 'provider:model'")
    provider, model, gen_settings, effort = resolved
    user_messages = [{"role": "user", "content": body.prompt}]
    try:
        result, _ = query_core.generate_from_hits(
            hits, user_messages, provider=provider, model=model, settings=gen_settings,
            reasoning_effort=effort)
    except llm.ProviderNotConfigured as e:
        raise HTTPException(status_code=400, detail=str(e))

    answer = (result.choices[0].message.content or "") + query_core.render_citations(hits)
    usage = result.usage.model_dump() if getattr(result, "usage", None) else None
    # The exact messages the model saw, so the Playground can show the assembled
    # prompt (retrieved chunks merged into the template). Same builder generate_from_hits()
    # uses internally with the same args, so this is identical — no drift.
    messages = query_core.augmented_messages(hits, user_messages)
    return {"answer": answer,
            "citations": query_core.serialize_pipeline_hits(ph, origins=origins),
            "usage": usage, "messages": messages}


@app.get("/corpora/{corpus_name}/pipelines", response_model=list[PipelineCard],
         responses={404: {"model": ErrorResponse}})
def list_pipelines(corpus_name: str, session: SessionDep):
    row = _corpus_row_or_404(session, corpus_name)
    docs = membership.member_documents(session, row.id)
    member_ids = [d.id for d in docs]
    effective_ids = set()
    for d in docs:
        eff = pipelines_mod.effective_pipeline(session, d)
        if eff is not None:
            effective_ids.add(eff.id)
    out = []
    for p in session.scalars(select(db.Pipeline).where(
            db.Pipeline.document_id.in_(member_ids)).order_by(db.Pipeline.id)):
        out.append({"name": p.name, "document_id": p.document_id, "slots": p.slots,
                    "rating": pipelines_mod.pipeline_rating(session, p.document_id, p.name),
                    "status": p.status, "effective": p.id in effective_ids})
    return out


# ---------------------------------------------------------------------------
# OpenAI-compatible shim
# ---------------------------------------------------------------------------

def _openai_error(status: int, message: str,
                  type_: str = "invalid_request_error") -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": {"message": message, "type": type_,
                                           "code": None}})


def _sse(stream, hits, model_name: str):
    """Yield OpenAI chat.completion.chunk SSE events, then a citations delta,
    then [DONE]. Mid-stream provider errors surface as a broken stream (v1)."""
    for chunk in stream:
        data = chunk.model_dump()
        data["model"] = model_name
        yield f"data: {json.dumps(data)}\n\n"
    footer = query_core.render_citations(hits)
    if footer:
        citation_chunk = {
            "id": "madosho-citations", "object": "chat.completion.chunk",
            "created": 0, "model": model_name,
            "choices": [{"index": 0, "delta": {"content": footer},
                         "finish_reason": None}],
        }
        yield f"data: {json.dumps(citation_chunk)}\n\n"
    yield "data: [DONE]\n\n"


class ChatMessage(BaseModel):
    role: str
    content: str | None = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model: str
    messages: list[ChatMessage]
    stream: bool = False


@app.get("/v1/models", response_model=ModelsResponse)
def list_models(session: SessionDep):
    vms = session.scalars(select(db.VirtualModel)).all()
    return {"object": "list",
            "data": [{"id": vm.name, "object": "model", "created": 0,
                      "owned_by": "madosho"}
                     for vm in vms]}


@app.post("/v1/chat/completions",
          responses={400: {"model": OpenAIErrorResponse},
                     404: {"model": OpenAIErrorResponse},
                     502: {"model": OpenAIErrorResponse}})
def chat_completions(body: ChatRequest, session: SessionDep, settings: SettingsDep):
    vm = session.scalar(select(db.VirtualModel).where(db.VirtualModel.name == body.model))
    if vm is None:
        return _openai_error(404, f"model '{body.model}' not found")
    corpus_row = session.get(db.Corpus, vm.corpus_id)
    if corpus_row is None:
        return _openai_error(404, "corpus for this model not found")

    user_messages = [m.model_dump() for m in body.messages]
    # Retrieval (multi-index) happens outside the provider try/except so a retrieval
    # or logic error is not mislabeled as a 502 "upstream provider error".
    ph = retrieval.multi_pipeline_query(
        session, corpus_row, query_core.last_user_text(user_messages),
        open_pipeline=_open_pipeline(settings))
    hits = [p.hit for p in ph]
    effort = endpoint_reasoning_effort(session, vm.provider, vm.model)
    try:
        result, _ = query_core.generate_from_hits(
            hits, user_messages, provider=vm.provider, model=vm.model,
            settings=settings, template=vm.template, stream=body.stream,
            reasoning_effort=effort)
    except llm.ProviderNotConfigured as e:
        return _openai_error(400, str(e))
    except Exception as e:  # upstream/provider failure (non-stream path)
        return _openai_error(502, f"upstream provider error: {e}", "api_error")

    if body.stream:
        return StreamingResponse(_sse(result, hits, body.model),
                                 media_type="text/event-stream")

    payload = result.model_dump()
    payload["model"] = body.model                      # report the virtual model name
    footer = query_core.render_citations(hits)
    if footer and payload.get("choices"):
        msg = payload["choices"][0].setdefault("message", {})
        msg["content"] = (msg.get("content") or "") + footer
    return payload
