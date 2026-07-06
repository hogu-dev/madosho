from __future__ import annotations

import base64
import binascii
import io
import json
import logging
import mimetypes
import os
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Annotated, Callable, Literal

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from madosho.core.config import MadoshoConfig
from madosho.core.errors import MadoshoError
from madosho.core.meta import ComponentKind
from madosho.core.registry import Registry
from madosho_server import cube as cube_mod, db, extraction, membership, pipelines, tasks, textdiff
from madosho_server import auth as auth_mod
from madosho_server.auth import make_auth_dependency
from madosho_server.components import list_components
from madosho_server.default_config import default_pipeline_config
from madosho_server.filestore import FileStore
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
    tasks.app.open()                # open the (defer-only) queue connector
    yield
    tasks.app.close()
    if db.engine is not None:
        db.engine.dispose()


# Control plane: safe methods need a read key; mutating methods need write. Every
# POST/PUT/PATCH/DELETE here is a genuine write, so the verb maps cleanly to the scope.
# (/auth/keys additionally requires the admin scope, via the same open_paths/scope seam.)
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_AUTH_OPEN = frozenset({"/health", "/auth/login", "/auth/logout", "/auth/me",
                        "/auth/me/password"})
control_auth = make_auth_dependency(
    lambda req: "write" if req.method in _UNSAFE_METHODS else "read",
    open_paths=_AUTH_OPEN)
app = FastAPI(title="madosho", lifespan=lifespan, dependencies=[Depends(control_auth)])


# ---- transactional-enqueue seam (overridable in tests) -------------------
def transactional_enqueue(session: Session, document_id: int) -> None:
    """Defer the ingest job on the SQLAlchemy session's own connection so the
    document row and the job commit together. Caller commits the session."""
    raw = session.connection().connection.driver_connection  # psycopg.Connection
    tasks.ingest_document.configure(connection=raw).defer(document_id=document_id)


def get_enqueue() -> Callable[[Session, int], None]:
    return transactional_enqueue


def transactional_enqueue_comparison(session: Session, document_id: int) -> None:
    """Defer the extraction head-to-head on the session's own connection so the
    job commits with the surrounding transaction. Caller commits the session."""
    raw = session.connection().connection.driver_connection  # psycopg.Connection
    tasks.run_extraction_comparison_task.configure(connection=raw).defer(document_id=document_id)


def get_enqueue_comparison() -> Callable[[Session, int], None]:
    return transactional_enqueue_comparison


def transactional_enqueue_eval(session: Session, eval_run_id: int) -> None:
    """Defer the eval run on the session's own connection so the run row and the
    job commit together."""
    raw = session.connection().connection.driver_connection  # psycopg.Connection
    tasks.run_eval.configure(connection=raw).defer(eval_run_id=eval_run_id)


def get_enqueue_eval() -> Callable[[Session, int], None]:
    return transactional_enqueue_eval


def transactional_enqueue_research(session: Session, research_run_id: int) -> None:
    """Defer the research run on the session's own connection so the run row and
    the job commit together."""
    raw = session.connection().connection.driver_connection  # psycopg.Connection
    tasks.run_research.configure(connection=raw).defer(research_run_id=research_run_id)


def get_enqueue_research() -> Callable[[Session, int], None]:
    return transactional_enqueue_research


def transactional_enqueue_alchemy(session: Session, alchemy_run_id: int) -> None:
    """Defer the alchemy run on the session's own connection so the run row and
    the job commit together (same discipline as research)."""
    raw = session.connection().connection.driver_connection  # psycopg.Connection
    tasks.run_alchemy.configure(connection=raw).defer(alchemy_run_id=alchemy_run_id)


def get_enqueue_alchemy() -> Callable[[Session, int], None]:
    return transactional_enqueue_alchemy


def transactional_enqueue_build_pipeline(session: Session, pipeline_id: int) -> None:
    """Defer the per-pipeline build on the session's own connection so the pipeline
    row and the job commit together. Caller commits."""
    raw = session.connection().connection.driver_connection  # psycopg.Connection
    tasks.build_pipeline.configure(connection=raw).defer(pipeline_id=pipeline_id)


def get_enqueue_build_pipeline() -> Callable[[Session, int], None]:
    return transactional_enqueue_build_pipeline


BuildPipelineEnqueueDep = Annotated[
    Callable[[Session, int], None], Depends(get_enqueue_build_pipeline)]


def transactional_enqueue_delete(session: Session,
                                 collections: list[str], file_uri: str) -> None:
    """Defer the document artifact cleanup on the session's own connection so the
    row deletion and the cleanup job commit together. Caller commits."""
    raw = session.connection().connection.driver_connection  # psycopg.Connection
    tasks.delete_document_artifacts.configure(connection=raw).defer(
        collections=collections, file_uri=file_uri)


def get_enqueue_delete() -> Callable[[Session, list, str], None]:
    return transactional_enqueue_delete


DeleteEnqueueDep = Annotated[
    Callable[[Session, list, str], None], Depends(get_enqueue_delete)]


# ---- schemas -------------------------------------------------------------
class CorpusCreate(BaseModel):
    # same pattern the kernel's MadoshoConfig.corpus enforces — fail fast here
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class CorpusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    config: dict


class CorpusMemberPipeline(BaseModel):
    """One of a member document's pipelines, as offered in the corpus page's
    per-document picker."""
    id: int
    name: str
    status: str
    rating: float | None = None
    is_default: bool             # the document's original ingest pipeline


class CorpusMember(BaseModel):
    """A document in a corpus, with its pipelines and which ones this corpus queries
    it through. `selected_pipeline_ids` is the corpus's explicit multi-select (empty =
    use the document's default); a query fans the document out across every selected
    pipeline and RRF-merges them. `default_pipeline_id` is what an empty selection
    resolves to (the document's effective/highest-rated pipeline)."""
    document_id: int
    filename: str
    status: str
    selected_pipeline_ids: list[int] = []
    default_pipeline_id: int | None = None
    pipelines: list[CorpusMemberPipeline] = []


class SelectPipelinesBody(BaseModel):
    pipeline_ids: list[int] = []     # empty clears the selection -> fall back to the default


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    filename: str
    status: str
    error: str | None = None
    progress: dict = {}   # live ingest feed: {phase, started_at, page_count, log:[{t,msg}]}
    selected_pipeline_id: int | None = None   # G: saved effective-pipeline override


class CorpusChip(BaseModel):
    id: int
    name: str


class DocumentDetailRead(DocumentRead):
    corpora: list[CorpusChip] = []   # the "in corpora" membership list


class LibraryDocumentRead(BaseModel):
    """A row in the global Documents library: the document plus its membership
    chips and its effective pipeline's summed rating (None until indexed)."""
    id: int
    filename: str
    status: str
    selected_pipeline_id: int | None = None
    corpora: list[CorpusChip] = []
    rating: float | None = None
    error: str | None = None
    progress: dict = {}   # live build feed of the building pipeline while indexing


class JobRead(BaseModel):
    """One row of the global Jobs feed (GET /jobs): a pipeline build across any
    document. Every build is a Pipeline row, so this covers both kinds -- a
    document's initial indexing IS its default pipeline's build (kind="ingest"),
    and every other pipeline is an added experiment (kind="build")."""
    kind: str                              # "ingest" (default pipeline) | "build"
    pipeline_id: int
    document_id: int
    document_filename: str
    name: str                              # pipeline name
    status: str                            # building | indexed | failed
    error: str | None = None
    progress: dict = {}                    # live build feed (phase + rolling log)
    created_at: datetime | None = None     # build start (server_default now())


class ReconfigureBody(BaseModel):
    """New recipe for a document's default pipeline (POST .../reconfigure). Slots
    left None keep their current value; options is {slot_kind: {opt: val}}."""
    parser: str | None = None
    chunker: str | None = None
    embedder: str | None = None
    options: dict[str, dict] = Field(default_factory=dict)


class DocumentIngest(BaseModel):
    """JSON body for POST /documents/ingest. content_b64 must be valid base64;
    decoded size is capped at 50 MB. corpus is resolved by name (404 if not found)."""
    filename: str
    content_b64: str
    corpus: str | None = None
    parser: str | None = None
    chunker: str | None = None
    embedder: str | None = None
    options: dict | None = None


class ChunkRead(BaseModel):
    id: str
    text: str
    position: int = 0
    page: int | None = None


class TableRead(BaseModel):
    content: str
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None  # reserved for L3


class ArtifactsRead(BaseModel):
    document_id: int
    chunks: list[ChunkRead]
    tables: list[TableRead]


class VirtualModelCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._@-]*$")
    corpus_id: int
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    template: str | None = None


class VirtualModelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: int
    name: str
    corpus_id: int
    provider: str
    model: str
    template: str | None


class LlmEndpointCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._@ -]*$")
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    api_base: str = Field(min_length=1)
    key_env_var: str | None = None
    supports_text: bool = True
    supports_vision: bool = False
    # "chat" = Chat Completions (default; what local servers speak);
    # "responses" = OpenAI Responses API (some frontier proxies need it for images)
    api_flavor: Literal["chat", "responses"] = "chat"

    @model_validator(mode="after")
    def _at_least_one_capability(self):
        if not self.supports_text and not self.supports_vision:
            raise ValueError("endpoint must support at least one of text/vision")
        return self


class LlmEndpointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: int
    name: str
    provider: str
    model: str
    api_base: str
    key_env_var: str | None
    is_default: bool
    key_present: bool
    supports_text: bool
    supports_vision: bool
    is_vision_default: bool
    api_flavor: str


SessionDep = Annotated[Session, Depends(db.get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
EnqueueDep = Annotated[Callable[[Session, int], None], Depends(get_enqueue)]
ComparisonEnqueueDep = Annotated[Callable[[Session, int], None], Depends(get_enqueue_comparison)]
EvalEnqueueDep = Annotated[Callable[[Session, int], None], Depends(get_enqueue_eval)]
ResearchEnqueueDep = Annotated[Callable[[Session, int], None], Depends(get_enqueue_research)]
AlchemyEnqueueDep = Annotated[Callable[[Session, int], None], Depends(get_enqueue_alchemy)]


class PipelineCreate(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    # Two shapes accepted: a full kernel `config` (CLI / e2e), OR a recipe
    # (parser/chunker/embedder) that the server overlays on the library
    # default base. Exactly the recipe path the web "+ New pipeline" form uses.
    config: dict | None = None
    parser: str | None = None
    chunker: str | None = None
    embedder: str | None = None
    # Per-slot tuning options, keyed by kernel kind: {"chunker": {"max_chars": 800}}.
    options: dict[str, dict] = Field(default_factory=dict)


class SelectedPipelineUpdate(BaseModel):
    pipeline_id: int | None = None


class ConfigUpdate(BaseModel):
    config: dict


class RatingsConfig(BaseModel):
    trigger: str = Field(pattern=r"^(on-demand|on-ingest)$")


class HumanVerdict(BaseModel):
    verdict: str = Field(pattern=r"^(a|b|tie)$")


class EvalLaunch(BaseModel):
    sampling: dict = Field(default_factory=dict)   # {n_docs, questions_per_doc, llm:{provider,model}}
    token_budget: int | None = None


class ResearchLaunch(BaseModel):
    prompt: str = Field(min_length=1)
    source: str = Field(default="rag", pattern=r"^(rag|whole-text)$")
    document_ids: list[int] = Field(default_factory=list)
    budget_chars: int = 100_000
    max_rounds: int = 8
    llm: dict = Field(default_factory=dict)   # {"provider","model"}


class StatusResponse(BaseModel):
    """Generic single-status ack (cancel, apply, dismiss, health)."""
    status: str


class RebuildResponse(BaseModel):
    rebuilding: int


class RunningResponse(BaseModel):
    running: int


class SelectedPipelineResponse(BaseModel):
    id: int
    selected_pipeline_id: int | None = None


class VerdictResponse(BaseModel):
    verdict: str | None = None


class ComponentCard(BaseModel):
    """One installed component (parser/chunker/embedder/...) for the config form.
    license/org/... are None for a component whose class failed to load."""
    name: str
    license: str | None = None
    org: str | None = None
    origin_tier: str | None = None
    hardware: str | None = None
    install_extra: str | None = None
    requires: dict[str, list[str]] = {}
    options_schema: dict | None = None


class DocumentPipelineCard(BaseModel):
    """A pipeline on the document page: slots, per-slot step ratings, summed
    rating, build status/progress, and whether it is the effective one."""
    id: int
    name: str
    slots: dict
    status: str
    is_default: bool
    steps: dict[str, float]
    rating: float | None = None
    effective: bool
    progress: dict
    created_at: str | None = None   # ISO build time, shown on the card + sorts newest-first


class RecommendedPipeline(BaseModel):
    """Advisory "recommended test": best tool per ingest slot across this
    document's indexed pipelines (D15 advice, never a verdict)."""
    slots: dict[str, str]
    steps: dict[str, float]
    projected_rating: float
    already_built: bool
    matches: str | None = None


class CreatePipelineResponse(BaseModel):
    id: int
    name: str
    document_id: int
    status: str
    collection: str | None = None
    slots: dict


class CubeCell(BaseModel):
    score: float
    source: str
    rationale: str | None = None
    suggestion: str | None = None


class PipelineRow(BaseModel):
    """One named pipeline on a document: its build-step cells + summed build score."""
    name: str
    pipeline_id: int
    effective: bool = False
    cells: dict[str, CubeCell]           # extraction / chunk / embed
    build_total: float


class DocGroup(BaseModel):
    """A document and the pipelines built on it. Retrieval (keyword/semantic/
    rerank) is rated per document today, so it sits on the group, not the rows."""
    document_id: int
    retrieval: dict[str, CubeCell]       # keyword / semantic / rerank
    retrieval_total: float
    pipelines: list[PipelineRow]


class CubeResponse(BaseModel):
    """The ratings cube: one group per document, one row per pipeline, plus weights."""
    documents: list[DocGroup]
    weights: dict[str, float]


class DiffSpans(BaseModel):
    """Word-level highlight spans on each side, as [start, end] char offsets."""
    a: list[tuple[int, int]]
    b: list[tuple[int, int]]


class ComparisonPage(BaseModel):
    page: int
    text_a: str
    text_b: str
    diff: DiffSpans
    change: int


class ComparisonResponse(BaseModel):
    """Extraction head-to-head (engine A vs engine B) for one document."""
    document_id: int
    engine_a: str
    text_a: str
    engine_b: str
    text_b: str
    verdict: str | None = None
    judge_verdict: str | None = None
    human_verdict: str | None = None
    judge_rationale: str | None = None
    judge_score: float | None = None
    diff: DiffSpans
    pages: list[ComparisonPage]


class PipelineExtractResponse(BaseModel):
    """Extract-stage diff between two of a document's pipelines (engine_a/b are
    the two pipeline NAMES). Same page/diff shape as ComparisonResponse."""
    document_id: int
    left_id: int
    right_id: int
    engine_a: str
    engine_b: str
    text_a: str
    text_b: str
    diff: DiffSpans
    pages: list[ComparisonPage]


class PipelineRef(BaseModel):
    id: int
    name: str


class ExtractColumn(BaseModel):
    """One pipeline's extraction of a page, with divergence-highlight spans."""
    pipeline_id: int
    name: str
    text: str
    spans: list[tuple[int, int]]   # char ranges where this text disagrees with >=1 other


class ExtractDivergencePage(BaseModel):
    page: int
    columns: list[ExtractColumn]
    change: int                    # total highlighted chars, drives the page-rail bars


class ExtractDivergenceResponse(BaseModel):
    """N-way extract comparison across a document's pipelines. A span is
    highlighted in a column when its text does not appear identically in every
    other column (a locus of disagreement) -- one flag, no baseline. Column order
    matches `pipelines`; each page carries one column per pipeline."""
    document_id: int
    pipelines: list[PipelineRef]
    pages: list[ExtractDivergencePage]


class EvalRunRead(BaseModel):
    id: int
    corpus_id: int
    status: str
    progress: dict | None = None
    sampling: dict | None = None
    token_budget: int | None = None
    tokens_spent: int | None = None
    cost_estimate: float | None = None
    cost_actual: float | None = None
    created_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    results: dict | list | None = None        # only on GET /evals/{run_id}


class EvalRunList(BaseModel):
    """Eval run as it appears in a LIST (omits the detail-only `results`)."""
    id: int
    corpus_id: int
    status: str
    progress: dict | None = None
    sampling: dict | None = None
    token_budget: int | None = None
    tokens_spent: int | None = None
    cost_estimate: float | None = None
    cost_actual: float | None = None
    created_at: str | None = None
    finished_at: str | None = None
    error: str | None = None


class ResearchRunRead(BaseModel):
    id: int
    corpus_id: int
    status: str
    progress: dict | None = None
    prompt: str
    config: dict | None = None
    stop_reason: str | None = None
    error: str | None = None
    created_at: str | None = None
    finished_at: str | None = None
    report_markdown: str | None = None        # only on the single-run GET (with_report)
    citations: list | None = None             # "
    run_log: list | None = None               # "


class ResearchRunList(BaseModel):
    """Research run as it appears in a LIST (omits the detail-only
    report_markdown / citations / run_log)."""
    id: int
    corpus_id: int
    status: str
    progress: dict | None = None
    prompt: str
    config: dict | None = None
    stop_reason: str | None = None
    error: str | None = None
    created_at: str | None = None
    finished_at: str | None = None


class AlchemyGoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    corpus_id: int
    goal_type: str = Field(default="living-research")
    spec: dict
    coverage: str = Field(default="search", pattern="^(search)$")  # stage A: search only


class AlchemyGoalRead(BaseModel):
    id: int
    name: str
    corpus_id: int
    goal_type: str
    spec: dict
    coverage: str
    created_at: str | None = None


class AlchemyRunLaunch(BaseModel):
    coverage: str | None = Field(default=None, pattern="^(search)$")  # defaults to the goal's coverage
    guidance: str | None = None
    based_on_version: int | None = None
    llm: dict                                   # {provider, model}
    budget_chars: int = 100_000
    max_rounds: int = 8
    max_llm_calls: int | None = Field(default=None, ge=1)  # optional self-cap for rate-limited upstreams


class AlchemyFinalize(BaseModel):
    version: int


class AlchemyRunRead(BaseModel):
    id: int
    goal_id: int
    version: int
    status: str
    coverage: str
    guidance: str | None = None
    based_on_version: int | None = None
    progress: dict | None = None
    stop_reason: str | None = None
    usage: dict | None = None
    is_final: bool = False
    error: str | None = None
    created_at: str | None = None
    finished_at: str | None = None
    draft_markdown: str | None = None           # only on the single-run GET
    citations: list | None = None               # "
    run_log: list | None = None                 # "
    sections: list | None = None                # only on the single-run GET


class AlchemyRunList(BaseModel):
    id: int
    goal_id: int
    version: int
    status: str
    coverage: str
    guidance: str | None = None
    based_on_version: int | None = None
    stop_reason: str | None = None
    usage: dict | None = None
    is_final: bool = False
    error: str | None = None
    created_at: str | None = None
    finished_at: str | None = None


class ProposalRead(BaseModel):
    id: int
    corpus_id: int
    eval_run_id: int | None = None
    proposed_config: dict | None = None
    evidence: dict | list | None = None
    status: str


def _reject_incompatible_recipe(config: dict) -> None:
    """Backstop for the upload paths: reject a recipe whose components can't run
    together (e.g. the docling-hybrid chunker without the docling parser) with a
    synchronous 422, instead of accepting the upload and failing the background
    build. The kernel's IngestSection validator is the actual rule; this just
    surfaces it as HTTP before any DB write."""
    try:
        MadoshoConfig(**config)
    except (MadoshoError, ValueError, TypeError) as e:
        raise HTTPException(status_code=422, detail=f"invalid recipe: {e}")


def _reject_invalid_options(config: dict) -> None:
    """Fail fast (HTTP 422) when a recipe carries per-component options that the
    component's Options model rejects (e.g. breakpoint_percentile=150) OR that
    use unknown option keys (typos that pydantic v2 silently ignores by default).
    Validates the ComponentRef mapping form `{name: {opts}}` against each slot's
    Options model; bare-string slots have no options to check. A component whose
    deps are not importable here is skipped (the worker build remains the
    backstop). Mirrors the unknown-key guard in Registry.resolve."""
    ingest = config.get("ingest", {})
    registry = Registry()
    registry.discover_entry_points()
    for slot, kind in (("parser", ComponentKind.PARSER),
                       ("chunker", ComponentKind.CHUNKER),
                       ("embedder", ComponentKind.EMBEDDER)):
        ref = ingest.get(slot)
        if not isinstance(ref, dict) or len(ref) != 1:
            continue
        (name, opts), = ref.items()
        try:
            cls = registry.load_class(kind, name)
        except Exception:
            continue   # not importable here; worker validates at build time
        opts_model = getattr(cls, "Options", None)
        if opts_model is None:
            continue
        # Reject unknown keys unless the model explicitly opts out (extra="allow").
        # Pydantic v2 silently ignores unknown keys by default, so a typo'd key
        # would otherwise pass here and only fail at the worker's Registry.resolve.
        opts_dict = opts or {}
        if opts_model.model_config.get("extra") != "allow":
            allowed: set[str] = set()
            for fname, f in opts_model.model_fields.items():
                allowed.add(fname)
                if isinstance(f.alias, str):
                    allowed.add(f.alias)
                if isinstance(f.validation_alias, str):
                    allowed.add(f.validation_alias)
            unknown = set(opts_dict) - allowed
            if unknown:
                raise HTTPException(
                    status_code=422,
                    detail=(f"unknown option(s) for {slot} '{name}': {sorted(unknown)}. "
                            f"Valid options: {sorted(allowed)}"))
        try:
            opts_model(**opts_dict)
        except (ValidationError, TypeError, ValueError) as e:
            raise HTTPException(status_code=422,
                                detail=f"invalid options for {slot} '{name}': {e}")


# ---- endpoints -----------------------------------------------------------
@app.get("/health", response_model=StatusResponse)
def health():
    return {"status": "ok"}


class LoginBody(BaseModel):
    key: str | None = None
    username: str | None = None
    password: str | None = None


@app.post("/auth/login")
def auth_login(body: LoginBody, response: Response,
               settings: Settings = Depends(get_settings)):
    """Exchange credentials for a signed httpOnly session cookie. Accepts a username +
    password (humans) or a raw API key (machines / break-glass)."""
    with db.SessionLocal() as session:
        if body.username is not None:
            user = auth_mod.verify_user_credentials(session, body.username, body.password or "")
            if user is None:
                raise HTTPException(401, "invalid username or password")
            user.last_login_at = datetime.now(timezone.utc)
            session.commit()
            principal = auth_mod.principal_from_user(user)
        elif body.key is not None:
            record = auth_mod.verify_key(session, body.key)
            if record is None:
                raise HTTPException(401, "invalid API key",
                                    headers={"WWW-Authenticate": "Bearer"})
            principal = auth_mod.principal_from_key(record)
        else:
            raise HTTPException(422, "provide username+password or key")
        auth_mod.issue_session_cookie(response, principal, settings)
        return {"scope": principal.scope, "name": principal.name, "kind": principal.kind}


@app.post("/auth/logout")
def auth_logout(response: Response):
    response.delete_cookie(auth_mod.SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/auth/me")
def auth_me(request: Request, settings: Settings = Depends(get_settings)):
    """Posture-aware: always 200. `auth_required` mirrors the server flag so the SPA
    can render an open UI when auth is disabled; `authenticated` reflects a valid
    cookie/bearer."""
    with db.SessionLocal() as session:
        principal, _ = auth_mod.resolve_principal(request, session, settings)
        if principal is not None:
            return {"authenticated": True, "auth_required": settings.auth_enabled,
                    "scope": principal.scope, "name": principal.name, "kind": principal.kind}
    return {"authenticated": False, "auth_required": settings.auth_enabled,
            "scope": None, "name": None, "kind": None}


class KeyCreate(BaseModel):
    name: str = Field(min_length=1)
    scope: str


class MintedKey(BaseModel):
    name: str
    prefix: str
    scope: str
    key: str                       # raw value, returned ONCE


class KeyRead(BaseModel):
    name: str
    prefix: str
    scope: str
    created_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None


@app.post("/auth/keys", response_model=MintedKey, status_code=201,
          dependencies=[Depends(auth_mod.require_admin)])
def mint_key(body: KeyCreate):
    if body.scope not in auth_mod.VALID_SCOPES:
        raise HTTPException(422, f"scope must be one of {auth_mod.VALID_SCOPES}")
    with db.SessionLocal() as session:
        try:
            raw = auth_mod.create_key(session, body.name, body.scope)
        except ValueError as e:
            raise HTTPException(409, str(e))
        return {"name": body.name, "prefix": raw[:12], "scope": body.scope, "key": raw}


@app.get("/auth/keys", response_model=list[KeyRead],
         dependencies=[Depends(auth_mod.require_admin)])
def list_api_keys():
    with db.SessionLocal() as session:
        return [
            {"name": k.name, "prefix": k.prefix, "scope": k.scope,
             "created_at": k.created_at, "last_used_at": k.last_used_at,
             "revoked_at": k.revoked_at}
            for k in auth_mod.list_keys(session)
        ]


@app.delete("/auth/keys/{name}", status_code=204,
            dependencies=[Depends(auth_mod.require_admin)])
def revoke_api_key(name: str):
    with db.SessionLocal() as session:
        try:
            auth_mod.revoke_key(session, name)
        except ValueError as e:
            msg = str(e)
            if "no key named" in msg:
                raise HTTPException(404, msg)
            raise HTTPException(409, msg)        # last-admin guard
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# User management endpoints
# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    username: str = Field(min_length=1)
    scope: str
    password: str = Field(min_length=1)


class UserRead(BaseModel):
    id: int
    username: str
    scope: str
    is_active: bool
    created_at: datetime | None
    last_login_at: datetime | None


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=1)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=1)


def _user_read(u) -> dict:
    return {"id": u.id, "username": u.username, "scope": u.scope, "is_active": u.is_active,
            "created_at": u.created_at, "last_login_at": u.last_login_at}


@app.post("/auth/users", response_model=UserRead, status_code=201,
          dependencies=[Depends(auth_mod.require_admin)])
def create_user_endpoint(body: UserCreate):
    if body.scope not in auth_mod.VALID_SCOPES:
        raise HTTPException(422, f"scope must be one of {auth_mod.VALID_SCOPES}")
    with db.SessionLocal() as session:
        try:
            user = auth_mod.create_user(session, body.username, body.password, body.scope)
        except ValueError as e:
            raise HTTPException(409, str(e))
        return _user_read(user)


@app.get("/auth/users", response_model=list[UserRead],
         dependencies=[Depends(auth_mod.require_admin)])
def list_users_endpoint():
    with db.SessionLocal() as session:
        return [_user_read(u) for u in auth_mod.list_users(session)]


@app.delete("/auth/users/{user_id}", status_code=204,
            dependencies=[Depends(auth_mod.require_admin)])
def deactivate_user_endpoint(user_id: int):
    with db.SessionLocal() as session:
        user = auth_mod.get_user_by_id(session, user_id)
        if user is None:
            raise HTTPException(404, f"no user with id {user_id}")
        try:
            auth_mod.deactivate_user(session, user)
        except ValueError as e:
            raise HTTPException(409, str(e))        # last-admin guard
    return Response(status_code=204)


@app.post("/auth/users/{user_id}/password", status_code=204,
          dependencies=[Depends(auth_mod.require_admin)])
def reset_user_password_endpoint(user_id: int, body: PasswordReset):
    with db.SessionLocal() as session:
        user = auth_mod.get_user_by_id(session, user_id)
        if user is None:
            raise HTTPException(404, f"no user with id {user_id}")
        auth_mod.set_password(session, user, body.new_password)
    return Response(status_code=204)


@app.post("/auth/me/password", status_code=204)
def change_my_password_endpoint(body: PasswordChange,
                                principal=Depends(auth_mod.current_principal)):
    if principal.kind != "user":
        raise HTTPException(400, "password change applies to user accounts only")
    with db.SessionLocal() as session:
        user = auth_mod.get_user_by_id(session, principal.id)
        if user is None or not auth_mod.verify_password(body.current_password, user.password_hash):
            raise HTTPException(403, "current password is incorrect")
        auth_mod.set_password(session, user, body.new_password)
    return Response(status_code=204)


@app.get("/components", response_model=dict[str, list[ComponentCard]])
def get_components():
    return list_components()


@app.post("/corpora", response_model=CorpusRead, status_code=201)
def create_corpus(body: CorpusCreate, session: SessionDep, settings: SettingsDep):
    if session.scalar(select(db.Corpus).where(db.Corpus.name == body.name)):
        raise HTTPException(status_code=409, detail=f"corpus '{body.name}' already exists")
    corpus = db.Corpus(name=body.name,
                       config=default_pipeline_config(body.name, settings.qdrant_url))
    session.add(corpus)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail=f"corpus '{body.name}' already exists")
    session.refresh(corpus)
    return corpus


@app.get("/corpora", response_model=list[CorpusRead])
def list_corpora(session: SessionDep):
    return session.scalars(select(db.Corpus).order_by(db.Corpus.id)).all()


@app.put("/corpora/{corpus_id}/config", response_model=CorpusRead)
def update_config(corpus_id: int, body: ConfigUpdate, session: SessionDep):
    corpus = session.get(db.Corpus, corpus_id)
    if corpus is None:
        raise HTTPException(status_code=404, detail="corpus not found")
    try:
        MadoshoConfig(**body.config)            # validate the recipe before saving
    except (MadoshoError, ValueError, TypeError) as e:
        raise HTTPException(status_code=422, detail=f"invalid config: {e}")
    corpus.config = body.config
    session.commit()
    session.refresh(corpus)
    return corpus


@app.post("/corpora/{corpus_id}/rebuild", status_code=202, response_model=RebuildResponse)
def rebuild_corpus(corpus_id: int, session: SessionDep, enqueue: EnqueueDep):
    if session.get(db.Corpus, corpus_id) is None:
        raise HTTPException(status_code=404, detail="corpus not found")
    docs = membership.member_documents(session, corpus_id)
    for doc in docs:
        doc.status = "received"
        doc.error = None
        enqueue(session, doc.id)
    session.commit()
    return {"rebuilding": len(docs)}


@app.get("/corpora/{corpus_id}/documents", response_model=list[DocumentRead])
def list_documents(corpus_id: int, session: SessionDep):
    if session.get(db.Corpus, corpus_id) is None:
        raise HTTPException(status_code=404, detail="corpus not found")
    return membership.member_documents(session, corpus_id)


@app.get("/corpora/{corpus_id}/members", response_model=list[CorpusMember])
def list_corpus_members(corpus_id: int, session: SessionDep):
    """The corpus page's member list: each document with its pipelines, the pipeline
    this corpus is pinned to (if any), and the default the corpus uses when unpinned."""
    if session.get(db.Corpus, corpus_id) is None:
        raise HTTPException(status_code=404, detail="corpus not found")
    selections = membership.membership_selections(session, corpus_id)
    out = []
    for d in membership.member_documents(session, corpus_id):
        eff = pipelines.effective_pipeline(session, d)
        out.append(CorpusMember(
            document_id=d.id, filename=d.filename, status=d.status,
            selected_pipeline_ids=selections.get(d.id, []),
            default_pipeline_id=eff.id if eff is not None else None,
            pipelines=[CorpusMemberPipeline(
                id=p.id, name=p.name, status=p.status, is_default=p.is_default,
                rating=pipelines.pipeline_rating(session, d.id, p.name))
                for p in pipelines.document_pipelines(session, d.id)]))
    return out


@app.put("/corpora/{corpus_id}/documents/{document_id}/pipelines", status_code=204)
def set_corpus_document_pipelines(corpus_id: int, document_id: int,
                                  body: SelectPipelinesBody, session: SessionDep):
    """Select which pipelines this corpus queries a member document through (an empty
    list clears the selection -> fall back to the document's default). A query fans the
    document out across every selected pipeline. 422 if any id is not one of the
    document's pipelines; 404 if the document is not a member of this corpus."""
    if session.get(db.Corpus, corpus_id) is None:
        raise HTTPException(status_code=404, detail="corpus not found")
    for pid in body.pipeline_ids:
        p = session.get(db.Pipeline, pid)
        if p is None or p.document_id != document_id:
            raise HTTPException(status_code=422, detail="pipeline not found for this document")
    if not membership.set_membership_pipelines(session, document_id, corpus_id, body.pipeline_ids):
        raise HTTPException(status_code=404, detail="document is not a member of this corpus")
    session.commit()


@app.post("/corpora/{corpus_id}/documents", response_model=DocumentRead, status_code=202)
def upload_document(corpus_id: int, file: UploadFile,
                    session: SessionDep, settings: SettingsDep, enqueue: EnqueueDep,
                    parser: str | None = Form(default=None),
                    chunker: str | None = Form(default=None),
                    embedder: str | None = Form(default=None),
                    name: str | None = Form(default=None),
                    options: str | None = Form(default=None)):
    if session.get(db.Corpus, corpus_id) is None:
        raise HTTPException(status_code=404, detail="corpus not found")

    filename = file.filename or "upload"
    store = FileStore(settings.filestore_dir)
    uri, digest = store.put_stream(filename, file.file)

    existing = session.scalar(select(db.Document).where(db.Document.content_hash == digest))
    if existing is not None:
        membership.add_membership(session, existing.id, corpus_id)   # membership-only (H4)
        session.commit()
        session.refresh(existing)
        return existing

    doc = db.Document(filename=filename, content_hash=digest,
                      file_uri=uri, mimetype=file.content_type or "application/octet-stream",
                      status="received")
    session.add(doc)
    try:
        session.flush()
        corpus_row = session.get(db.Corpus, corpus_id)
        opts = json.loads(options) if options else None
        config = tasks.recipe_config(corpus_row.config, parser=parser,
                                     chunker=chunker, embedder=embedder, options=opts)
        _reject_incompatible_recipe(config)        # 422 on a recipe that can't run
        _reject_invalid_options(config)            # 422 on a bad option value
        pname = name or pipelines.default_pipeline_name(filename)
        tasks.create_pipeline_from_config(session, doc, config, pname, is_default=True)
        membership.add_membership(session, doc.id, corpus_id)
        enqueue(session, doc.id)                       # index ONCE, deferred in the SAME txn
        session.commit()                               # atomic: row + membership + pipeline + job
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(db.Document).where(
            db.Document.content_hash == digest))
        if existing is None:
            # No competing row by content_hash -> this was NOT a hash race. Some other
            # constraint fired (e.g. pipeline / procrastinate insert); don't mislabel it
            # as a retryable race. Log the real cause and surface a truthful 500.
            logger.exception("upload_document: non-race IntegrityError (no competing hash)")
            raise HTTPException(status_code=500, detail="upload failed; see server logs")
        membership.add_membership(session, existing.id, corpus_id)   # genuine race: winner exists
        session.commit()
        session.refresh(existing)
        return existing
    session.refresh(doc)
    return doc


@app.post("/corpora/{corpus_id}/documents/{document_id}", response_model=DocumentRead)
def add_document_to_corpus(corpus_id: int, document_id: int, session: SessionDep):
    """Add an existing library document to a corpus (membership only; never
    re-indexes - H4). Idempotent."""
    if session.get(db.Corpus, corpus_id) is None:
        raise HTTPException(status_code=404, detail="corpus not found")
    doc = session.get(db.Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    membership.add_membership(session, document_id, corpus_id)
    session.commit()
    session.refresh(doc)
    return doc


@app.delete("/corpora/{corpus_id}/documents/{document_id}", status_code=204)
def remove_document_from_corpus(corpus_id: int, document_id: int, session: SessionDep):
    """Remove a document's membership in a corpus. Does NOT delete the document -
    it stays in the library even after its last membership is removed (H4)."""
    if session.get(db.Corpus, corpus_id) is None:
        raise HTTPException(status_code=404, detail="corpus not found")
    membership.remove_membership(session, document_id, corpus_id)
    session.commit()


@app.get("/documents", response_model=list[LibraryDocumentRead])
def list_library_documents(session: SessionDep):
    """The global library: every document, with its membership chips and the
    effective pipeline's summed rating."""
    out = []
    for doc in session.scalars(select(db.Document).order_by(db.Document.id)):
        eff = pipelines.effective_pipeline(session, doc)
        rating = pipelines.pipeline_rating(session, doc.id, eff.name) if eff else None
        chips = [CorpusChip(id=c.id, name=c.name)
                 for c in membership.document_corpora(session, doc.id)]
        # Surface the live build feed on the list so Documents can show a console
        # while indexing -- the feed lives on whichever pipeline is building.
        progress: dict = {}
        if doc.status in ("received", "indexing"):
            building = next((p for p in pipelines.document_pipelines(session, doc.id)
                             if p.status == "building"), None)
            if building is not None:
                progress = building.progress or {}
        out.append(LibraryDocumentRead(
            id=doc.id, filename=doc.filename, status=doc.status,
            selected_pipeline_id=doc.selected_pipeline_id, corpora=chips, rating=rating,
            error=doc.error, progress=progress))
    return out


# Global Jobs feed shows every in-flight build plus this many most-recent finished
# ones, so a build you navigated away from stays visible long enough to confirm it
# succeeded or failed. Tunable: raise for a longer history, lower for a tighter list.
JOBS_TERMINAL_LIMIT = 30


@app.get("/jobs", response_model=list[JobRead])
def list_jobs(session: SessionDep):
    """The global activity feed: every pipeline build across all documents that is
    in flight, plus the most-recent finished ones, newest first. A default
    pipeline's build is the document's ingest (kind="ingest"); the rest are added
    experiments (kind="build"). Running jobs always show; finished jobs are capped
    at JOBS_TERMINAL_LIMIT so the list doesn't grow without bound."""
    rows = session.execute(
        select(db.Pipeline, db.Document.filename)
        .join(db.Document, db.Pipeline.document_id == db.Document.id)
        .order_by(db.Pipeline.created_at.desc(), db.Pipeline.id.desc())
    ).all()
    out: list[JobRead] = []
    terminal = 0
    for p, filename in rows:
        if p.status != "building":                 # finished (indexed/failed): keep recent ones only
            if terminal >= JOBS_TERMINAL_LIMIT:
                continue
            terminal += 1
        out.append(JobRead(
            kind="ingest" if p.is_default else "build",
            pipeline_id=p.id, document_id=p.document_id, document_filename=filename,
            name=p.name, status=p.status, error=p.error, progress=p.progress or {},
            created_at=p.created_at))
    return out


def _resolve_corpus_id_or_404(session: Session, name: str) -> int:
    """Resolve a corpus NAME to its integer id, raising 404 if not found."""
    corpus = session.scalar(select(db.Corpus).where(db.Corpus.name == name))
    if corpus is None:
        raise HTTPException(status_code=404, detail=f"corpus '{name}' not found")
    return corpus.id


def _ingest_bytes(
        session: Session, settings: Settings,
        enqueue: Callable, enqueue_build: Callable, *,
        content: bytes, filename: str, mimetype: str, corpus_id: int | None,
        parser: str | None, chunker: str | None, embedder: str | None,
        name: str | None, options: dict | None) -> db.Document:
    """Store bytes by SHA-256, find-or-create the library document, create or
    reuse a named pipeline from the recipe, optionally attach a corpus
    membership, and return the document. Caller must commit.

    This is the shared core for both the multipart (POST /documents) and
    base64-JSON (POST /documents/ingest) upload paths. The two paths differ
    only in how bytes arrive; all transaction logic lives here.

    Behaviour for an existing document (hash already known):
    - Creates an additional named pipeline if the recipe is new, then enqueues
      a build for that pipeline.
    - Adds corpus membership if corpus_id is given.

    Behaviour for a new document:
    - Stores the file, creates the default pipeline, enqueues a full ingest,
      and adds corpus membership if corpus_id is given.
    - Handles the concurrent-insert IntegrityError race transparently.
    """
    store = FileStore(settings.filestore_dir)
    uri, digest = store.put_stream(filename, io.BytesIO(content))

    base = default_pipeline_config(LIBRARY_LABEL, settings.qdrant_url)
    config = tasks.recipe_config(base, parser=parser, chunker=chunker,
                                 embedder=embedder, options=options)
    _reject_incompatible_recipe(config)          # 422 on a recipe that can't run
    _reject_invalid_options(config)              # 422 on a bad option value
    pname = name or pipelines.default_pipeline_name(filename)

    existing = session.scalar(
        select(db.Document).where(db.Document.content_hash == digest))
    if existing is not None:
        before = session.scalar(select(db.Pipeline).where(
            db.Pipeline.document_id == existing.id, db.Pipeline.name == pname))
        p = tasks.create_pipeline_from_config(session, existing, config, pname)
        if before is None:                       # a NEW named pipeline -> build just it
            enqueue_build(session, p.id)
        if corpus_id is not None:
            membership.add_membership(session, existing.id, corpus_id)
        session.commit()
        session.refresh(existing)
        return existing

    doc = db.Document(filename=filename, content_hash=digest, file_uri=uri,
                      mimetype=mimetype, status="received")
    session.add(doc)
    try:
        session.flush()                          # assign doc.id inside the txn
        tasks.create_pipeline_from_config(session, doc, config, pname, is_default=True)
        if corpus_id is not None:
            membership.add_membership(session, doc.id, corpus_id)
        enqueue(session, doc.id)                 # ingest builds the default pipeline
        session.commit()                         # atomic: row + pipeline + membership + job
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(db.Document).where(
            db.Document.content_hash == digest))
        if existing is None:
            # Not a content_hash race (no competing row); a different constraint fired.
            # Surface the real error truthfully instead of a misleading "upload race".
            logger.exception("_ingest_bytes: non-race IntegrityError (no competing hash)")
            raise HTTPException(status_code=500, detail="upload failed; see server logs")
        if corpus_id is not None:
            membership.add_membership(session, existing.id, corpus_id)
        session.commit()
        session.refresh(existing)                # genuine race: another upload won, reuse its doc
        return existing
    session.refresh(doc)
    return doc


@app.post("/documents", response_model=DocumentRead, status_code=202)
def upload_library_document(
        file: UploadFile, session: SessionDep, settings: SettingsDep,
        enqueue: EnqueueDep, enqueue_build: BuildPipelineEnqueueDep,
        parser: str | None = Form(default=None),
        chunker: str | None = Form(default=None),
        embedder: str | None = Form(default=None),
        name: str | None = Form(default=None),
        options: str | None = Form(default=None)):
    """Library upload (H5/H6): file + chosen recipe (parser/chunker/embedder).
    Find-or-create the document by content hash across the whole library, then
    find-or-create a NAMED pipeline from the recipe. A brand-new document is
    indexed once; an existing document gets the recipe as an additional named
    pipeline (built on its own), or a no-op if that name already exists. No
    corpus membership is written here - add the doc to corpora afterward."""
    filename = file.filename or "upload"
    content = file.file.read()
    opts = json.loads(options) if options else None
    return _ingest_bytes(session, settings, enqueue, enqueue_build,
                         content=content, filename=filename,
                         mimetype=file.content_type or "application/octet-stream",
                         corpus_id=None,
                         parser=parser, chunker=chunker, embedder=embedder,
                         name=name, options=opts)


@app.post("/documents/ingest", response_model=DocumentRead, status_code=202)
def ingest_document(body: DocumentIngest, session: SessionDep, settings: SettingsDep,
                    enqueue: EnqueueDep, enqueue_build: BuildPipelineEnqueueDep):
    """Base64-JSON upload: decode content_b64, find-or-create the library
    document by SHA-256, optionally attach a corpus membership, and enqueue
    ingest. Behaviour is identical to POST /documents (multipart) - same
    helper, same transaction shape, same race handling."""
    try:
        content = base64.b64decode(body.content_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="content_b64 is not valid base64")
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="file exceeds the 50 MB inline cap")
    corpus_id = _resolve_corpus_id_or_404(session, body.corpus) if body.corpus else None
    return _ingest_bytes(session, settings, enqueue, enqueue_build,
                         content=content, filename=body.filename,
                         mimetype=mimetypes.guess_type(body.filename)[0] or "application/octet-stream",
                         corpus_id=corpus_id,
                         parser=body.parser, chunker=body.chunker, embedder=body.embedder,
                         name=None, options=body.options)


@app.get("/documents/{document_id}", response_model=DocumentDetailRead)
def get_document(document_id: int, session: SessionDep):
    doc = session.get(db.Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    chips = [CorpusChip(id=c.id, name=c.name)
             for c in membership.document_corpora(session, document_id)]
    return DocumentDetailRead(
        id=doc.id, filename=doc.filename, status=doc.status, error=doc.error,
        progress=doc.progress or {}, selected_pipeline_id=doc.selected_pipeline_id,
        corpora=chips)


@app.get("/documents/{document_id}/pipelines", response_model=list[DocumentPipelineCard])
def list_document_pipelines(document_id: int, session: SessionDep):
    """This document's pipelines for the doc page: slots, per-slot step ratings,
    summed rating, status, is_default, and which one is effective."""
    doc = session.get(db.Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    eff = pipelines.effective_pipeline(session, doc)
    eff_id = eff.id if eff is not None else None
    out = []
    for p in pipelines.document_pipelines(session, document_id):
        out.append({
            "id": p.id, "name": p.name, "slots": p.slots, "status": p.status,
            "is_default": p.is_default,
            "steps": pipelines.step_ratings_by_slot(session, document_id, p.name),
            "rating": pipelines.pipeline_rating(session, document_id, p.name),
            "effective": p.id == eff_id,
            "progress": p.progress or {},   # live build feed (phase + rolling log)
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })
    return out


@app.get("/documents/{document_id}/recommended-pipeline", response_model=RecommendedPipeline | None)
def get_recommended_pipeline(document_id: int, session: SessionDep):
    """The advisory "recommended test" for the compare view: the best tool per
    ingest slot across this document's indexed pipelines, assembled into a combo
    worth building. null when there is nothing to suggest. Never auto-built."""
    doc = session.get(db.Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return pipelines.recommended_pipeline(session, document_id)


@app.put("/documents/{document_id}/selected-pipeline", response_model=SelectedPipelineResponse)
def set_selected_pipeline(document_id: int, body: SelectedPipelineUpdate, session: SessionDep):
    """Save (or clear, with null) the document's effective-pipeline override. None
    falls back to the highest-rated pipeline. A non-null id must name a pipeline of
    THIS document (any status); effective_pipeline() ignores it until it is indexed."""
    doc = session.get(db.Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    if body.pipeline_id is not None:
        p = session.get(db.Pipeline, body.pipeline_id)
        if p is None or p.document_id != document_id:
            raise HTTPException(status_code=422, detail="pipeline not found for this document")
    doc.selected_pipeline_id = body.pipeline_id
    session.commit()
    session.refresh(doc)
    return {"id": doc.id, "selected_pipeline_id": doc.selected_pipeline_id}


@app.post("/documents/{document_id}/rebuild", status_code=202, response_model=StatusResponse)
def rebuild_document(document_id: int, session: SessionDep, enqueue: EnqueueDep):
    """Re-run ingest for one document (retry a failed build, or re-index after a
    transient outage). Resets the doc to a pending state and re-enqueues; the
    task reuses the document's default pipeline. Same recipe as before -- to
    change the recipe, delete and re-upload, or build a new named pipeline."""
    doc = session.get(db.Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    doc.status = "received"
    doc.error = None
    enqueue(session, doc.id)
    session.commit()
    return {"status": "rebuilding"}


@app.post("/documents/{document_id}/reconfigure", status_code=202, response_model=StatusResponse)
def reconfigure_document(document_id: int, body: ReconfigureBody, session: SessionDep,
                         enqueue: EnqueueDep):
    """Re-choose the recipe for a document's default pipeline and rebuild it in
    place (e.g. swap a failed contextual recipe for docling-hybrid). Applies the
    new slots onto the pipeline's existing config -- keeping its collection and
    query stack -- validates, then re-enqueues ingest. The default pipeline is
    reused, so its collection/ratings identity is preserved."""
    doc = session.get(db.Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    pipeline = session.scalar(select(db.Pipeline).where(
        db.Pipeline.document_id == document_id, db.Pipeline.is_default.is_(True)))
    if pipeline is None:
        raise HTTPException(status_code=404, detail="document has no default pipeline")
    config = tasks.recipe_config(pipeline.config, parser=body.parser, chunker=body.chunker,
                                 embedder=body.embedder, options=body.options or None)
    config = tasks._with_collection(config, pipeline.collection)
    _reject_invalid_options(config)                # 422 on a bad/unknown option value
    try:
        MadoshoConfig(**config)                    # validate before saving
    except (MadoshoError, ValueError, TypeError) as e:
        raise HTTPException(status_code=422, detail=f"invalid config: {e}")
    pipeline.config = config
    pipeline.slots = pipelines.slots_from_config(config)
    pipeline.status, pipeline.error = "building", None
    doc.status, doc.error = "received", None
    enqueue(session, doc.id)                        # ingest rebuilds the default pipeline
    session.commit()
    return {"status": "rebuilding"}


@app.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: int, session: SessionDep, enqueue_delete: DeleteEnqueueDep):
    """Remove a document: its DB row + rating/comparison/eval-question/pipeline
    children and its corpus membership + per-corpus pipeline pins now (no DB cascade
    is configured), and - deferred to the worker - each pipeline's vector collection
    and the file blob."""
    doc = session.get(db.Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    file_uri = doc.file_uri
    collections = [p.collection for p in session.scalars(
        select(db.Pipeline).where(db.Pipeline.document_id == document_id)) if p.collection]
    for child in (db.TechniqueRating, db.ExtractionComparison, db.EvalQuestion,
                  db.DocumentCorpus, db.DocumentCorpusPipeline):
        session.execute(delete(child).where(child.document_id == document_id))
    session.execute(delete(db.Pipeline).where(db.Pipeline.document_id == document_id))
    session.delete(doc)
    enqueue_delete(session, collections, file_uri)  # defer cleanup in the SAME txn
    session.commit()


@app.delete("/documents/{document_id}/pipelines/{pipeline_id}", status_code=204)
def delete_pipeline(document_id: int, pipeline_id: int, session: SessionDep,
                    enqueue_delete: DeleteEnqueueDep):
    """Delete one pipeline: its row now, its Qdrant collection deferred to the
    worker. Technique ratings and extraction comparisons are document-scoped and
    shared with sibling pipelines (keyed by document + technique, not pipeline),
    so they are deliberately left untouched. The file blob is kept -- the document
    still owns it, which is exactly what protects the blob in the deferred cleanup.
    If this was the document's selected pipeline, the selection is cleared so the
    effective pipeline falls back to the highest-rated one."""
    doc = session.get(db.Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    p = session.get(db.Pipeline, pipeline_id)
    if p is None or p.document_id != document_id:
        raise HTTPException(status_code=404, detail="pipeline not found for this document")
    if doc.selected_pipeline_id == p.id:
        doc.selected_pipeline_id = None              # fall back to the highest-rated
    collection = p.collection
    session.delete(p)
    if collection:                                   # drop this pipeline's vectors; blob survives (doc remains)
        enqueue_delete(session, [collection], doc.file_uri)
    session.commit()


@app.post("/documents/{document_id}/pipelines", status_code=202, response_model=CreatePipelineResponse)
def create_pipeline(document_id: int, body: PipelineCreate, session: SessionDep,
                    settings: SettingsDep, enqueue: BuildPipelineEnqueueDep):
    doc = session.get(db.Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    if session.scalar(select(db.Pipeline).where(
            db.Pipeline.document_id == document_id, db.Pipeline.name == body.name)):
        raise HTTPException(status_code=409,
                            detail=f"pipeline '{body.name}' already exists for this document")
    if body.config is not None:
        config = body.config                       # full kernel config (CLI / e2e)
    else:                                          # recipe path (web "+ New pipeline")
        base = default_pipeline_config(LIBRARY_LABEL, settings.qdrant_url)
        config = tasks.recipe_config(base, parser=body.parser,
                                     chunker=body.chunker, embedder=body.embedder,
                                     options=body.options)
    _reject_invalid_options(config)                # 422 on bad/unknown option (both paths)
    try:
        MadoshoConfig(**config)                    # validate the config before saving
    except (MadoshoError, ValueError, TypeError) as e:
        raise HTTPException(status_code=422, detail=f"invalid config: {e}")
    p = db.Pipeline(document_id=doc.id, name=body.name,
                    config={}, slots={}, status="building", is_default=False)
    session.add(p)
    session.flush()                                # assign p.id
    collection = tasks._pipeline_collection(p.id)
    p.collection = collection
    p.config = tasks._with_collection(config, collection)
    p.slots = pipelines.slots_from_config(p.config)
    enqueue(session, p.id)
    session.commit()
    session.refresh(p)
    return {"id": p.id, "name": p.name, "document_id": p.document_id,
            "status": p.status, "collection": p.collection, "slots": p.slots}


# Cosmetic corpus label stamped into a library document's pipeline config. The
# real index lives in the per-pipeline collection (madosho_p{id}); this label is
# only the kernel config's `corpus` field, which never scopes retrieval after H.
LIBRARY_LABEL = "library"

# Types a browser renders without executing script. Deliberately excludes
# text/html and image/svg+xml (both can carry script) -- those download instead.
INLINE_SAFE_MIMETYPES = frozenset({
    "application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "text/plain",
})


@app.get("/documents/{document_id}/file")
def get_document_file(document_id: int, session: SessionDep, settings: SettingsDep):
    doc = session.get(db.Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    path = FileStore(settings.filestore_dir).path_for(doc.file_uri)
    if not path.exists():
        raise HTTPException(status_code=404, detail="file missing from store")
    # Uploads are user-controlled bytes served from the app's own origin, so an
    # `inline` text/html or image/svg+xml would execute as stored XSS in that
    # origin. Only render passively-displayed types inline (so the comparison
    # viewer's original pane shows a PDF instead of force-downloading); force
    # everything else to download. nosniff stops a mislabeled file being sniffed
    # into HTML. The doc page's "Download original" button works regardless via
    # the HTML `download` attribute.
    inline = doc.mimetype in INLINE_SAFE_MIMETYPES
    return FileResponse(
        path, media_type=doc.mimetype, filename=doc.filename,
        content_disposition_type="inline" if inline else "attachment",
        headers={"X-Content-Type-Options": "nosniff"})


@app.get("/documents/{document_id}/artifacts", response_model=ArtifactsRead)
def get_artifacts(document_id: int, session: SessionDep):
    doc = session.get(db.Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    if not doc.artifacts:
        raise HTTPException(status_code=409,
                            detail="no parsed artifacts for this document — re-process to view")
    art = doc.artifacts
    chunks = [ChunkRead(id=c["id"], text=c["text"],
                        position=c.get("position", 0), page=c.get("page"))
              for c in art.get("chunks", [])]
    tables = [TableRead(content=b["content"], page=b["provenance"].get("page"),
                        bbox=b["provenance"].get("bbox"))
              for b in art.get("blocks", []) if b.get("kind") == "table"]
    return ArtifactsRead(document_id=document_id, chunks=chunks, tables=tables)


@app.get("/pipelines/{pipeline_id}/artifacts", response_model=ArtifactsRead)
def get_pipeline_artifacts(pipeline_id: int, session: SessionDep):
    """This pipeline's OWN extracted chunks/tables (each built pipeline persists
    its own artifacts), so the doc page can drill into the output of the specific
    pipeline being viewed rather than the document's original ingest."""
    p = session.get(db.Pipeline, pipeline_id)
    if p is None:
        raise HTTPException(status_code=404, detail="pipeline not found")
    if not p.artifacts:
        raise HTTPException(status_code=409,
                            detail="no artifacts for this pipeline — still building or failed")
    art = p.artifacts
    chunks = [ChunkRead(id=c["id"], text=c["text"],
                        position=c.get("position", 0), page=c.get("page"))
              for c in art.get("chunks", [])]
    tables = [TableRead(content=b["content"], page=b["provenance"].get("page"),
                        bbox=b["provenance"].get("bbox"))
              for b in art.get("blocks", []) if b.get("kind") == "table"]
    return ArtifactsRead(document_id=p.document_id, chunks=chunks, tables=tables)


@app.get("/corpora/{corpus_id}/ratings", response_model=CubeResponse)
def get_ratings(corpus_id: int, session: SessionDep):
    if session.get(db.Corpus, corpus_id) is None:
        raise HTTPException(status_code=404, detail="corpus not found")
    member_docs = membership.member_documents(session, corpus_id)
    member_ids = [d.id for d in member_docs]
    rows = session.scalars(
        select(db.TechniqueRating).where(
            or_(
                db.TechniqueRating.document_id.in_(member_ids),
                and_(db.TechniqueRating.corpus_id == corpus_id,
                     db.TechniqueRating.document_id.is_(None)),
            ))).all()
    dicts = [{"document_id": r.document_id, "dimension": r.dimension, "score": r.score,
              "source": r.source, "candidate_config": r.candidate_config,
              "rationale": r.rationale, "suggestion": r.suggestion}
             for r in rows]

    # Per-document pipeline metadata drives the grouping: which pipelines to show,
    # in id order, and which one the document answers through by default. Only
    # documents that carry at least one pipeline become groups.
    pipeline_meta: dict[int, list[dict]] = {}
    for doc in member_docs:
        pipes = pipelines.document_pipelines(session, doc.id)
        if not pipes:
            continue
        eff = pipelines.effective_pipeline(session, doc)
        eff_id = eff.id if eff is not None else None
        pipeline_meta[doc.id] = [
            {"name": p.name, "pipeline_id": p.id, "effective": p.id == eff_id}
            for p in pipes]
    return cube_mod.assemble_cube(dicts, pipeline_meta)


@app.get("/corpora/{corpus_id}/ratings/config", response_model=RatingsConfig)
def get_ratings_config(corpus_id: int, session: SessionDep):
    corpus = session.get(db.Corpus, corpus_id)
    if corpus is None:
        raise HTTPException(status_code=404, detail="corpus not found")
    return RatingsConfig(**(corpus.ratings_config or {"trigger": "on-demand"}))


@app.put("/corpora/{corpus_id}/ratings/config", response_model=RatingsConfig)
def put_ratings_config(corpus_id: int, body: RatingsConfig, session: SessionDep):
    corpus = session.get(db.Corpus, corpus_id)
    if corpus is None:
        raise HTTPException(status_code=404, detail="corpus not found")
    corpus.ratings_config = body.model_dump()
    session.commit()
    return body


@app.post("/corpora/{corpus_id}/ratings/run", status_code=202, response_model=RunningResponse)
def run_ratings(corpus_id: int, session: SessionDep, enqueue: ComparisonEnqueueDep):
    if session.get(db.Corpus, corpus_id) is None:
        raise HTTPException(status_code=404, detail="corpus not found")
    docs = membership.member_documents(session, corpus_id, indexed_only=True)
    for doc in docs:
        enqueue(session, doc.id)
    session.commit()
    return {"running": len(docs)}


@app.get("/documents/{document_id}/comparison", response_model=ComparisonResponse)
def get_comparison(document_id: int, session: SessionDep):
    comp = session.scalar(select(db.ExtractionComparison)
                          .where(db.ExtractionComparison.document_id == document_id)
                          .order_by(db.ExtractionComparison.id.desc()))
    if comp is None:
        raise HTTPException(status_code=404, detail="no comparison for this document")

    def page_payload(page_no: int, ta: str, tb: str) -> dict:
        diff = textdiff.diff_spans(ta or "", tb or "")
        # `change` = total highlighted characters on both sides; the rail sizes its
        # per-page marker by this, so pages with only tiny variation stay quiet.
        change = (sum(e - s for s, e in diff["a"]) + sum(e - s for s, e in diff["b"]))
        return {"page": page_no, "text_a": ta, "text_b": tb, "diff": diff, "change": change}

    if comp.pages:
        pages = [page_payload(p.get("page", i + 1), p.get("text_a", ""), p.get("text_b", ""))
                 for i, p in enumerate(comp.pages)]
    else:  # whole-document fallback: one synthetic page over the flat text
        pages = [page_payload(1, comp.text_a, comp.text_b)]

    return {
        "document_id": document_id,
        "engine_a": comp.engine_a, "text_a": comp.text_a,
        "engine_b": comp.engine_b, "text_b": comp.text_b,
        "verdict": comp.human_verdict or comp.judge_verdict,
        "judge_verdict": comp.judge_verdict, "human_verdict": comp.human_verdict,
        "judge_rationale": comp.judge_rationale, "judge_score": comp.judge_score,
        "diff": textdiff.diff_spans(comp.text_a, comp.text_b),
        "pages": pages,
    }


@app.post("/documents/{document_id}/comparison/verdict", response_model=VerdictResponse)
def post_verdict(document_id: int, body: HumanVerdict, session: SessionDep):
    comp = session.scalar(select(db.ExtractionComparison)
                          .where(db.ExtractionComparison.document_id == document_id)
                          .order_by(db.ExtractionComparison.id.desc()))
    if comp is None:
        raise HTTPException(status_code=404, detail="no comparison for this document")
    comp.human_verdict = body.verdict
    doc = session.get(db.Document, document_id)
    # Human verdict picks the winning side; faithfulness defaults to judge score
    # (or 3.0 mid if the run was human-only). source='human' outranks 'measured' in the cube.
    session.execute(delete(db.TechniqueRating).where(  # one human row per cell
        db.TechniqueRating.document_id == document_id,
        db.TechniqueRating.dimension == "extraction",
        db.TechniqueRating.source == "human"))
    session.add(db.TechniqueRating(
        document_id=document_id, dimension="extraction",
        candidate_config=f"human:{body.verdict}",
        score=comp.judge_score if comp.judge_score is not None else 3.0,
        source="human", rationale="Human override", rater_version="human-v1"))
    session.commit()
    return {"verdict": comp.human_verdict}


@app.get("/documents/{document_id}/pipeline-extract", response_model=PipelineExtractResponse)
def get_pipeline_extract_diff(document_id: int, left: int, right: int, session: SessionDep):
    """Extract-stage diff between two of this document's pipelines.

    Reads each pipeline's STORED artifacts (`pipeline.artifacts.blocks`) and diffs
    them page-aligned — never a re-parse. Same word-level, whitespace-insensitive
    machinery as the legacy head-to-head (`textdiff.diff_spans`), so the page rail
    and Raw/Rendered viewer reuse the existing `ComparisonPage` shape unchanged;
    `engine_a`/`engine_b` are the two pipeline names rather than parser engines.
    """
    doc = session.get(db.Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")

    def _pipe(pid: int) -> db.Pipeline:
        p = session.get(db.Pipeline, pid)
        if p is None or p.document_id != document_id:
            raise HTTPException(status_code=404,
                                detail=f"pipeline {pid} is not on this document")
        if not p.artifacts:
            raise HTTPException(status_code=409,
                                detail=f"pipeline '{p.name}' has no artifacts yet — still building or failed")
        return p

    lp, rp = _pipe(left), _pipe(right)
    a_pages = extraction._docling_pages(lp.artifacts)   # {page: extracted text}
    b_pages = extraction._docling_pages(rp.artifacts)

    def page_payload(page_no: int, ta: str, tb: str) -> dict:
        diff = textdiff.diff_spans(ta or "", tb or "")
        change = sum(e - s for s, e in diff["a"]) + sum(e - s for s, e in diff["b"])
        return {"page": page_no, "text_a": ta, "text_b": tb, "diff": diff, "change": change}

    pages = [page_payload(n, a_pages.get(n, ""), b_pages.get(n, ""))
             for n in sorted(set(a_pages) | set(b_pages))]
    text_a = "\n\n".join(a_pages[n] for n in sorted(a_pages))
    text_b = "\n\n".join(b_pages[n] for n in sorted(b_pages))
    return {
        "document_id": document_id, "left_id": left, "right_id": right,
        "engine_a": lp.name, "engine_b": rp.name,
        "text_a": text_a, "text_b": text_b,
        "diff": textdiff.diff_spans(text_a, text_b),
        "pages": pages,
    }


@app.get("/documents/{document_id}/extract-divergence",
         response_model=ExtractDivergenceResponse)
def get_extract_divergence(
    document_id: int,
    session: SessionDep,
    ids: Annotated[list[int], Query()],
):
    """N-way extract comparison across `ids` (>=2 of this document's pipelines).

    Same stored-artifacts, word-level, whitespace-insensitive machinery as the
    2-way `pipeline-extract`, but generalised: per page, a column's highlight
    spans are the loci where its text differs from at least one other column
    (`textdiff.divergence_spans`). One highlight, no baseline -- the UI reads the
    columns to see which pipeline is the odd one out.
    """
    doc = session.get(db.Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    if len(ids) < 2:
        raise HTTPException(status_code=400,
                            detail="need at least two pipelines to compare")

    def _pipe(pid: int) -> db.Pipeline:
        p = session.get(db.Pipeline, pid)
        if p is None or p.document_id != document_id:
            raise HTTPException(status_code=404,
                                detail=f"pipeline {pid} is not on this document")
        if not p.artifacts:
            raise HTTPException(status_code=409,
                                detail=f"pipeline '{p.name}' has no artifacts yet — still building or failed")
        return p

    pipes = [_pipe(pid) for pid in ids]
    pages_by_pipe = [extraction._docling_pages(p.artifacts) for p in pipes]
    all_pages = sorted(set().union(*(set(pp) for pp in pages_by_pipe)))

    out_pages = []
    for pg in all_pages:
        texts = [pp.get(pg, "") for pp in pages_by_pipe]
        spans = textdiff.divergence_spans(texts)
        columns = [{"pipeline_id": pipes[k].id, "name": pipes[k].name,
                    "text": texts[k], "spans": spans[k]}
                   for k in range(len(pipes))]
        change = sum(e - s for col in spans for s, e in col)
        out_pages.append({"page": pg, "columns": columns, "change": change})

    return {"document_id": document_id,
            "pipelines": [{"id": p.id, "name": p.name} for p in pipes],
            "pages": out_pages}


# ---- eval serialization helpers ------------------------------------------
def _eval_run_dict(run: "db.EvalRun", with_results: bool = False) -> dict:
    out = {"id": run.id, "corpus_id": run.corpus_id, "status": run.status,
           "progress": run.progress, "sampling": run.sampling,
           "token_budget": run.token_budget,
           "tokens_spent": run.tokens_spent, "cost_estimate": run.cost_estimate,
           "cost_actual": run.cost_actual,
           "created_at": run.created_at.isoformat() if run.created_at else None,
           "finished_at": run.finished_at.isoformat() if run.finished_at else None,
           "error": run.error}
    if with_results:
        out["results"] = run.results
    return out


def _research_run_dict(run: "db.ResearchRun", with_report: bool = False) -> dict:
    out = {"id": run.id, "corpus_id": run.corpus_id, "status": run.status,
           "progress": run.progress, "prompt": run.prompt, "config": run.config,
           "stop_reason": run.stop_reason, "error": run.error,
           "created_at": run.created_at.isoformat() if run.created_at else None,
           "finished_at": run.finished_at.isoformat() if run.finished_at else None}
    if with_report:
        out["report_markdown"] = run.report_markdown
        out["citations"] = run.citations
        out["run_log"] = run.run_log
    return out


def _iso(dt):
    return dt.isoformat() if dt is not None else None


def _alchemy_goal_dict(g: "db.AlchemyGoal") -> dict:
    return {"id": g.id, "name": g.name, "corpus_id": g.corpus_id,
            "goal_type": g.goal_type, "spec": g.spec, "coverage": g.coverage,
            "created_at": _iso(g.created_at)}


def _alchemy_run_dict(r: "db.AlchemyRun", with_draft: bool = False) -> dict:
    d = {"id": r.id, "goal_id": r.goal_id, "version": r.version,
         "status": r.status, "coverage": r.coverage, "guidance": r.guidance,
         "based_on_version": r.based_on_version, "progress": r.progress,
         "stop_reason": r.stop_reason, "usage": r.usage, "is_final": r.is_final,
         "error": r.error, "created_at": _iso(r.created_at),
         "finished_at": _iso(r.finished_at)}
    if with_draft:
        d.update(draft_markdown=r.draft_markdown, citations=r.citations,
                 run_log=r.run_log, sections=r.sections)
    return d


def _resolve_goal(session, ref: str):
    """A goal ref is its numeric id or its unique name."""
    g = None
    if ref.isdigit():
        g = session.get(db.AlchemyGoal, int(ref))
    if g is None:
        g = session.scalars(select(db.AlchemyGoal)
                            .where(db.AlchemyGoal.name == ref)).first()
    return g


def _proposal_dict(p: "db.ConfigProposal") -> dict:
    return {"id": p.id, "corpus_id": p.corpus_id, "eval_run_id": p.eval_run_id,
            "proposed_config": p.proposed_config, "evidence": p.evidence,
            "status": p.status}


# ---- eval endpoints -------------------------------------------------------
@app.post("/corpora/{corpus_id}/evals", status_code=201, response_model=EvalRunRead)
def launch_eval(corpus_id: int, body: EvalLaunch, session: SessionDep, enqueue: EvalEnqueueDep):
    if session.get(db.Corpus, corpus_id) is None:
        raise HTTPException(status_code=404, detail="corpus not found")
    run = db.EvalRun(corpus_id=corpus_id, status="pending",
                     sampling=body.sampling, token_budget=body.token_budget,
                     progress={"phase": "pending"})
    session.add(run)
    session.flush()
    enqueue(session, run.id)
    session.commit()
    session.refresh(run)
    return _eval_run_dict(run)


@app.get("/corpora/{corpus_id}/evals", response_model=list[EvalRunList])
def list_evals(corpus_id: int, session: SessionDep):
    if session.get(db.Corpus, corpus_id) is None:
        raise HTTPException(status_code=404, detail="corpus not found")
    runs = session.scalars(select(db.EvalRun).where(db.EvalRun.corpus_id == corpus_id)
                           .order_by(db.EvalRun.id.desc())).all()
    return [_eval_run_dict(r) for r in runs]


@app.get("/evals/{run_id}", response_model=EvalRunRead)
def get_eval(run_id: int, session: SessionDep):
    run = session.get(db.EvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="eval run not found")
    return _eval_run_dict(run, with_results=True)


@app.post("/evals/{run_id}/cancel", response_model=StatusResponse)
def cancel_eval(run_id: int, session: SessionDep):
    run = session.get(db.EvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="eval run not found")
    if run.status in ("pending", "running"):
        run.status = "cancelled"
        session.commit()
    return {"status": run.status}


# ---- research endpoints ---------------------------------------------------
@app.post("/corpora/{corpus_id}/research", status_code=201, response_model=ResearchRunRead)
def launch_research(corpus_id: int, body: ResearchLaunch, session: SessionDep,
                    enqueue: ResearchEnqueueDep):
    if session.get(db.Corpus, corpus_id) is None:
        raise HTTPException(status_code=404, detail="corpus not found")
    if not body.llm.get("provider") or not body.llm.get("model"):
        raise HTTPException(status_code=400, detail="llm provider and model are required")
    run = db.ResearchRun(
        corpus_id=corpus_id, status="pending", prompt=body.prompt,
        config={"source": body.source, "document_ids": body.document_ids,
                "budget_chars": body.budget_chars, "max_rounds": body.max_rounds,
                "llm": body.llm},
        progress={"phase": "pending"})
    session.add(run)
    session.flush()
    enqueue(session, run.id)
    session.commit()
    session.refresh(run)
    return _research_run_dict(run)


@app.get("/corpora/{corpus_id}/research", response_model=list[ResearchRunList])
def list_research(corpus_id: int, session: SessionDep):
    if session.get(db.Corpus, corpus_id) is None:
        raise HTTPException(status_code=404, detail="corpus not found")
    runs = session.scalars(select(db.ResearchRun)
                           .where(db.ResearchRun.corpus_id == corpus_id)
                           .order_by(db.ResearchRun.id.desc())).all()
    return [_research_run_dict(r) for r in runs]


@app.get("/corpora/{corpus_id}/research/{run_id}", response_model=ResearchRunRead)
def get_research(corpus_id: int, run_id: int, session: SessionDep):
    run = session.get(db.ResearchRun, run_id)
    if run is None or run.corpus_id != corpus_id:
        raise HTTPException(status_code=404, detail="research run not found")
    return _research_run_dict(run, with_report=True)


@app.post("/research/{run_id}/cancel", response_model=StatusResponse)
def cancel_research(run_id: int, session: SessionDep):
    run = session.get(db.ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="research run not found")
    if run.status in ("pending", "running"):
        run.status = "cancelled"
        session.commit()
    return {"status": run.status}


# ---- alchemy endpoints -----------------------------------------------------
@app.post("/alchemy/goals", status_code=201, response_model=AlchemyGoalRead)
def create_alchemy_goal(body: AlchemyGoalCreate, session: SessionDep):
    if session.get(db.Corpus, body.corpus_id) is None:
        raise HTTPException(status_code=404, detail="corpus not found")
    if body.goal_type not in ("living-research", "report"):
        raise HTTPException(
            status_code=400,
            detail="goal_type must be 'living-research' or 'report'")
    if body.goal_type == "living-research":
        goal_val = (body.spec or {}).get("goal", "")
        if not isinstance(goal_val, str) or not goal_val.strip():
            raise HTTPException(status_code=400, detail="spec.goal is required")
    else:
        # fail-fast: an uncompilable template should 400 at create time, not
        # fail a run later. Lazy import keeps api module import light; the
        # server importing alchemy is the allowed dependency direction.
        from alchemy.compile import compile_spec
        try:
            compile_spec("report", body.spec or {})
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    # name-only lookup: _resolve_goal's id-then-name resolution would spuriously
    # match an unrelated goal by id when body.name happens to be all digits
    existing = session.scalars(select(db.AlchemyGoal)
                               .where(db.AlchemyGoal.name == body.name)).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="goal name already exists")
    goal = db.AlchemyGoal(name=body.name, corpus_id=body.corpus_id,
                          goal_type=body.goal_type, spec=body.spec,
                          coverage=body.coverage)
    session.add(goal)
    session.commit()
    session.refresh(goal)
    return _alchemy_goal_dict(goal)


@app.get("/alchemy/goals", response_model=list[AlchemyGoalRead])
def list_alchemy_goals(session: SessionDep):
    goals = session.scalars(select(db.AlchemyGoal)
                            .order_by(db.AlchemyGoal.id.desc())).all()
    return [_alchemy_goal_dict(g) for g in goals]


@app.get("/alchemy/goals/{ref}", response_model=AlchemyGoalRead)
def get_alchemy_goal(ref: str, session: SessionDep):
    g = _resolve_goal(session, ref)
    if g is None:
        raise HTTPException(status_code=404, detail="goal not found")
    return _alchemy_goal_dict(g)


@app.delete("/alchemy/goals/{ref}", response_model=StatusResponse)
def delete_alchemy_goal(ref: str, session: SessionDep):
    g = _resolve_goal(session, ref)
    if g is None:
        raise HTTPException(status_code=404, detail="goal not found")
    session.query(db.AlchemyRun).filter(db.AlchemyRun.goal_id == g.id).delete()
    session.delete(g)
    session.commit()
    return {"status": "deleted"}


@app.post("/alchemy/goals/{ref}/runs", status_code=201, response_model=AlchemyRunRead)
def start_alchemy_run(ref: str, body: AlchemyRunLaunch, session: SessionDep,
                      enqueue: AlchemyEnqueueDep):
    g = _resolve_goal(session, ref)
    if g is None:
        raise HTTPException(status_code=404, detail="goal not found")
    if not body.llm.get("provider") or not body.llm.get("model"):
        raise HTTPException(status_code=400, detail="llm provider and model are required")
    last = session.scalars(select(db.AlchemyRun)
                           .where(db.AlchemyRun.goal_id == g.id)
                           .order_by(db.AlchemyRun.version.desc())).first()
    version = (last.version + 1) if last else 1
    prior_draft_version = body.based_on_version
    if prior_draft_version is None:
        # default: revise the highest-version run of this goal that actually
        # has a draft, not just the newest run overall (a later run may have
        # failed before producing one)
        draft_run = session.scalars(
            select(db.AlchemyRun)
            .where(db.AlchemyRun.goal_id == g.id,
                   db.AlchemyRun.draft_markdown.isnot(None),
                   db.AlchemyRun.draft_markdown != "")
            .order_by(db.AlchemyRun.version.desc())).first()
        if draft_run is not None:
            prior_draft_version = draft_run.version
    run = db.AlchemyRun(
        goal_id=g.id, version=version, status="pending",
        coverage=body.coverage or g.coverage, guidance=body.guidance,
        based_on_version=prior_draft_version,
        progress={"phase": "pending"},
        config={"llm": body.llm, "budget_chars": body.budget_chars,
                "max_rounds": body.max_rounds, "max_llm_calls": body.max_llm_calls})
    session.add(run)
    session.flush()
    enqueue(session, run.id)
    session.commit()
    session.refresh(run)
    return _alchemy_run_dict(run)


@app.get("/alchemy/goals/{ref}/runs", response_model=list[AlchemyRunList])
def list_alchemy_runs(ref: str, session: SessionDep):
    g = _resolve_goal(session, ref)
    if g is None:
        raise HTTPException(status_code=404, detail="goal not found")
    runs = session.scalars(select(db.AlchemyRun)
                           .where(db.AlchemyRun.goal_id == g.id)
                           .order_by(db.AlchemyRun.version.desc())).all()
    return [_alchemy_run_dict(r) for r in runs]


@app.get("/alchemy/goals/{ref}/runs/{version}", response_model=AlchemyRunRead)
def get_alchemy_run(ref: str, version: int, session: SessionDep):
    g = _resolve_goal(session, ref)
    if g is None:
        raise HTTPException(status_code=404, detail="goal not found")
    run = session.scalars(select(db.AlchemyRun)
                          .where(db.AlchemyRun.goal_id == g.id,
                                 db.AlchemyRun.version == version)).first()
    if run is None:
        raise HTTPException(status_code=404, detail="run version not found")
    return _alchemy_run_dict(run, with_draft=True)


@app.post("/alchemy/goals/{ref}/finalize", response_model=AlchemyRunRead)
def finalize_alchemy_run(ref: str, body: AlchemyFinalize, session: SessionDep):
    g = _resolve_goal(session, ref)
    if g is None:
        raise HTTPException(status_code=404, detail="goal not found")
    run = session.scalars(select(db.AlchemyRun)
                          .where(db.AlchemyRun.goal_id == g.id,
                                 db.AlchemyRun.version == body.version)).first()
    if run is None:
        raise HTTPException(status_code=404, detail="run version not found")
    # one final version at a time: clear any prior final on this goal
    session.query(db.AlchemyRun).filter(
        db.AlchemyRun.goal_id == g.id, db.AlchemyRun.is_final == True).update(  # noqa: E712
        {"is_final": False})
    run.is_final = True
    session.commit()
    session.refresh(run)
    return _alchemy_run_dict(run, with_draft=True)


@app.post("/alchemy/runs/{run_id}/cancel", response_model=StatusResponse)
def cancel_alchemy_run(run_id: int, session: SessionDep):
    run = session.get(db.AlchemyRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status in ("pending", "running"):
        run.status = "cancelled"
        session.commit()
    return {"status": run.status}


@app.get("/corpora/{corpus_id}/proposal", response_model=ProposalRead | None)
def get_proposal(corpus_id: int, session: SessionDep):
    p = session.scalar(select(db.ConfigProposal)
                       .where(db.ConfigProposal.corpus_id == corpus_id,
                              db.ConfigProposal.status == "proposed")
                       .order_by(db.ConfigProposal.id.desc()))
    if p is None:
        raise HTTPException(status_code=404, detail="no active proposal")
    return _proposal_dict(p)


@app.post("/proposals/{proposal_id}/dismiss", response_model=StatusResponse)
def dismiss_proposal_endpoint(proposal_id: int, session: SessionDep):
    from madosho_server.eval import proposal as proposal_mod
    if session.get(db.ConfigProposal, proposal_id) is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    proposal_mod.dismiss_proposal(session, proposal_id)
    session.commit()
    return {"status": "dismissed"}


@app.post("/virtual-models", response_model=VirtualModelRead, status_code=201)
def create_virtual_model(body: VirtualModelCreate, session: SessionDep):
    if session.get(db.Corpus, body.corpus_id) is None:
        raise HTTPException(status_code=404, detail="corpus not found")
    if session.scalar(select(db.VirtualModel).where(db.VirtualModel.name == body.name)):
        raise HTTPException(status_code=409,
                            detail=f"virtual model '{body.name}' already exists")
    vm = db.VirtualModel(name=body.name, corpus_id=body.corpus_id,
                         provider=body.provider, model=body.model,
                         template=body.template)
    session.add(vm)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409,
                            detail=f"virtual model '{body.name}' already exists")
    session.refresh(vm)
    return vm


@app.get("/virtual-models", response_model=list[VirtualModelRead])
def list_virtual_models(session: SessionDep):
    return session.scalars(select(db.VirtualModel).order_by(db.VirtualModel.id)).all()


@app.get("/virtual-models/{vm_id}", response_model=VirtualModelRead)
def get_virtual_model(vm_id: int, session: SessionDep):
    vm = session.get(db.VirtualModel, vm_id)
    if vm is None:
        raise HTTPException(status_code=404, detail="virtual model not found")
    return vm


@app.delete("/virtual-models/{vm_id}", status_code=204)
def delete_virtual_model(vm_id: int, session: SessionDep):
    vm = session.get(db.VirtualModel, vm_id)
    if vm is None:
        raise HTTPException(status_code=404, detail="virtual model not found")
    session.delete(vm)
    session.commit()


def _endpoint_read(row: db.LlmEndpoint) -> LlmEndpointRead:
    present = bool(row.key_env_var) and os.environ.get(row.key_env_var) is not None
    return LlmEndpointRead(id=row.id, name=row.name, provider=row.provider,
        model=row.model, api_base=row.api_base, key_env_var=row.key_env_var,
        is_default=row.is_default, key_present=present,
        supports_text=row.supports_text, supports_vision=row.supports_vision,
        is_vision_default=row.is_vision_default, api_flavor=row.api_flavor)


@app.post("/llm-endpoints", response_model=LlmEndpointRead, status_code=201)
def create_llm_endpoint(body: LlmEndpointCreate, session: SessionDep):
    if session.scalar(select(db.LlmEndpoint).where(db.LlmEndpoint.name == body.name)):
        raise HTTPException(409, detail=f"endpoint '{body.name}' already exists")
    first = session.query(db.LlmEndpoint).count() == 0
    has_vision_default = session.scalar(
        select(db.LlmEndpoint).where(db.LlmEndpoint.is_vision_default.is_(True))) is not None
    row = db.LlmEndpoint(name=body.name, provider=body.provider, model=body.model,
        api_base=body.api_base, key_env_var=body.key_env_var, is_default=first,
        supports_text=body.supports_text, supports_vision=body.supports_vision,
        is_vision_default=(body.supports_vision and not has_vision_default),
        api_flavor=body.api_flavor)
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, detail=f"endpoint '{body.name}' already exists")
    session.refresh(row)
    return _endpoint_read(row)


@app.get("/llm-endpoints", response_model=list[LlmEndpointRead])
def list_llm_endpoints(session: SessionDep):
    rows = session.scalars(select(db.LlmEndpoint).order_by(db.LlmEndpoint.id)).all()
    return [_endpoint_read(r) for r in rows]


@app.put("/llm-endpoints/{endpoint_id}", response_model=LlmEndpointRead)
def update_llm_endpoint(endpoint_id: int, body: LlmEndpointCreate, session: SessionDep):
    row = session.get(db.LlmEndpoint, endpoint_id)
    if row is None:
        raise HTTPException(404, detail="endpoint not found")
    row.name, row.provider, row.model = body.name, body.provider, body.model
    row.api_base, row.key_env_var = body.api_base, body.key_env_var
    row.supports_text, row.supports_vision = body.supports_text, body.supports_vision
    row.api_flavor = body.api_flavor
    if not body.supports_vision:
        row.is_vision_default = False
    if not body.supports_text:
        row.is_default = False
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, detail=f"endpoint '{body.name}' already exists")
    session.refresh(row)
    return _endpoint_read(row)


@app.put("/llm-endpoints/{endpoint_id}/default", response_model=LlmEndpointRead)
def set_default_llm_endpoint(endpoint_id: int, session: SessionDep):
    if session.get(db.LlmEndpoint, endpoint_id) is None:
        raise HTTPException(404, detail="endpoint not found")
    try:
        row = db.set_default_endpoint(session, endpoint_id)
    except ValueError as e:
        raise HTTPException(422, detail=str(e))
    return _endpoint_read(row)


@app.put("/llm-endpoints/{endpoint_id}/vision-default", response_model=LlmEndpointRead)
def set_vision_default_llm_endpoint(endpoint_id: int, session: SessionDep):
    if session.get(db.LlmEndpoint, endpoint_id) is None:
        raise HTTPException(404, detail="endpoint not found")
    try:
        row = db.set_vision_default_endpoint(session, endpoint_id)
    except ValueError as e:
        raise HTTPException(422, detail=str(e))
    return _endpoint_read(row)


@app.delete("/llm-endpoints/{endpoint_id}", status_code=204)
def delete_llm_endpoint(endpoint_id: int, session: SessionDep):
    row = session.get(db.LlmEndpoint, endpoint_id)
    if row is None:
        raise HTTPException(404, detail="endpoint not found")
    was_default = row.is_default
    session.delete(row); session.commit()
    if was_default:
        nxt = session.scalars(select(db.LlmEndpoint).order_by(db.LlmEndpoint.id)).first()
        if nxt is not None:
            db.set_default_endpoint(session, nxt.id)
