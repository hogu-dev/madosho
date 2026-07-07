from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, create_engine, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker,
)

# JSONB on Postgres, portable JSON on SQLite (tests).
JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class Corpus(Base):
    __tablename__ = "corpus"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    config: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    ratings_config: Mapped[dict] = mapped_column(
        JSON_TYPE, default=lambda: {"trigger": "on-demand"})

class Document(Base):
    __tablename__ = "document"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(512))
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    file_uri: Mapped[str] = mapped_column(String(1024))
    mimetype: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="received")
    error: Mapped[str | None] = mapped_column(default=None)
    kernel_doc_id: Mapped[str | None] = mapped_column(String(128), default=None, index=True)
    artifacts: Mapped[dict | None] = mapped_column(JSON_TYPE, default=None)
    traits: Mapped[dict | None] = mapped_column(JSON_TYPE, default=None)
    # live ingest progress for the UI: {phase, started_at, page_count, log:[{t,msg}]}
    progress: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    # G: saved UI override for the document's effective pipeline. None = use the
    # highest-rated pipeline (computed default). Plain int (no ORM FK) on purpose:
    # a real FK to pipeline.id would form a create-table cycle with
    # Pipeline.document_id and break create_all() on SQLite. Integrity is enforced
    # in application code (pipelines.effective_pipeline ignores stale/non-indexed ids).
    selected_pipeline_id: Mapped[int | None] = mapped_column(default=None)
    # Liveness signal for the stalled-job sweeper: updated by the progress reporter
    # on every write, so a live job is never swept; a SIGKILLed job stops writing,
    # this freezes, and the sweeper fails it past ceiling + grace.
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Pipeline(Base):
    __tablename__ = "pipeline"
    __table_args__ = (UniqueConstraint("document_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("document.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))                # user-given; unique (document_id, name)
    config: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)  # FULL kernel config (collection set)
    collection: Mapped[str] = mapped_column(String(255), default="")  # this pipeline's Qdrant collection
    slots: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)   # {extract, chunk, index} tool names (display)
    status: Mapped[str] = mapped_column(String(16), default="building")  # building|indexed|failed
    error: Mapped[str | None] = mapped_column(Text, default=None)
    progress: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)  # live build feed (phase + rolling log); owned by the reporter
    is_default: Mapped[bool] = mapped_column(default=False)        # the auto-created docling pipeline
    kernel_doc_id: Mapped[str | None] = mapped_column(String(128), default=None)
    artifacts: Mapped[dict | None] = mapped_column(JSON_TYPE, default=None)  # chunks/blocks (drill-downs)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # Liveness signal for the stalled-job sweeper: updated by the progress reporter
    # on every write, so a live job is never swept; a SIGKILLed job stops writing,
    # this freezes, and the sweeper fails it past ceiling + grace.
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class DocumentCorpus(Base):
    """Many-to-many membership: a document belongs to many corpora; a corpus is a
    set of documents. Adding/removing membership never re-indexes (H4)."""
    __tablename__ = "document_corpus"
    __table_args__ = (UniqueConstraint("document_id", "corpus_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("document.id"), index=True)
    corpus_id: Mapped[int] = mapped_column(ForeignKey("corpus.id"), index=True)
    # Legacy single-pin column (one pipeline per member). Superseded by the
    # document_corpus_pipeline selection table, which lets a corpus query a document
    # through SEVERAL pipelines at once. Kept so existing rows migrate forward (see
    # _ensure_added_columns); no longer read at resolve time.
    pipeline_id: Mapped[int | None] = mapped_column(default=None)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DocumentCorpusPipeline(Base):
    """The SET of pipelines THIS corpus queries a member document through (multi-select).
    Each row is one selected pipeline for a (corpus, document) pair; querying fans the
    document out across all of them and RRF-merges the per-pipeline results. NO rows for
    a (corpus, document) means "use the document's default pipeline". Plain ints, no ORM
    FK to Pipeline (like the other pipeline references) -- a stale/non-indexed id is
    tolerated and skipped at resolve time, the selection is a preference, not a lock."""
    __tablename__ = "document_corpus_pipeline"
    __table_args__ = (UniqueConstraint("corpus_id", "document_id", "pipeline_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    corpus_id: Mapped[int] = mapped_column(ForeignKey("corpus.id"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("document.id"), index=True)
    pipeline_id: Mapped[int] = mapped_column()


class VirtualModel(Base):
    __tablename__ = "virtual_model"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    corpus_id: Mapped[int] = mapped_column(ForeignKey("corpus.id"))
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(255))
    # None -> query_core falls back to its DEFAULT_TEMPLATE
    template: Mapped[str | None] = mapped_column(Text, default=None)


class LlmEndpoint(Base):
    __tablename__ = "llm_endpoint"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(255))
    api_base: Mapped[str] = mapped_column(String(512))
    # the NAME of the env var holding the API key (value lives in .env, never here)
    key_env_var: Mapped[str | None] = mapped_column(String(255), default=None)
    is_default: Mapped[bool] = mapped_column(default=False)
    supports_text: Mapped[bool] = mapped_column(default=True)
    supports_vision: Mapped[bool] = mapped_column(default=False)
    is_vision_default: Mapped[bool] = mapped_column(default=False)
    # Which OpenAI-style API surface the server behind api_base speaks: "chat"
    # (Chat Completions, the de-facto standard local servers implement) or
    # "responses" (OpenAI's newer Responses API). Some frontier-model proxies
    # only handle multimodal input on the responses surface.
    api_flavor: Mapped[str] = mapped_column(String(16), default="chat")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class ApiKey(Base):
    __tablename__ = "api_key"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)   # human label, e.g. "ci-uploader"
    prefix: Mapped[str] = mapped_column(String(16), index=True)   # leading chars, display/lookup only
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # sha256 hex of the raw key
    scope: Mapped[str] = mapped_column(String(8))                 # "read" | "write" | "admin"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None)                   # best-effort, set on use (Task 5)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None)                   # null = active


class User(Base):
    __tablename__ = "app_user"          # "user" is reserved in PostgreSQL

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    scope: Mapped[str] = mapped_column(String(8))                 # read|write|admin
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None)


class TechniqueRating(Base):
    __tablename__ = "technique_rating"

    id: Mapped[int] = mapped_column(primary_key=True)
    corpus_id: Mapped[int | None] = mapped_column(ForeignKey("corpus.id"), default=None, index=True)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("document.id"), default=None, index=True)   # None = corpus rollup
    dimension: Mapped[str] = mapped_column(String(32))         # extraction/chunk/embed/keyword/semantic/rerank
    candidate_config: Mapped[str | None] = mapped_column(String(255), default=None)
    score: Mapped[float] = mapped_column()
    source: Mapped[str] = mapped_column(String(16))            # static/measured/human/f-empirical
    rationale: Mapped[str | None] = mapped_column(Text, default=None)
    suggestion: Mapped[str | None] = mapped_column(Text, default=None)
    rater_version: Mapped[str] = mapped_column(String(32), default="static-v1")


class ExtractionComparison(Base):
    __tablename__ = "extraction_comparison"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("document.id"), index=True)
    engine_a: Mapped[str] = mapped_column(String(64))
    text_a: Mapped[str] = mapped_column(Text)
    engine_b: Mapped[str] = mapped_column(String(64))
    text_b: Mapped[str] = mapped_column(Text)
    judge_model: Mapped[str | None] = mapped_column(String(64), default=None)   # None = awaiting human
    judge_verdict: Mapped[str | None] = mapped_column(String(8), default=None)  # a/b/tie
    judge_score: Mapped[float | None] = mapped_column(default=None)             # winner faithfulness 0-5
    judge_confidence: Mapped[float | None] = mapped_column(default=None)
    judge_rationale: Mapped[str | None] = mapped_column(Text, default=None)
    human_verdict: Mapped[str | None] = mapped_column(String(8), default=None)  # a/b/tie
    # Optional per-page segmentation: [{"page", "text_a", "text_b"}, ...]. When
    # present the viewer compares a page at a time; when None it falls back to the
    # whole-document text_a/text_b above.
    pages: Mapped[list | None] = mapped_column(JSON_TYPE, default=None)


class EvalRun(Base):
    __tablename__ = "eval_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    corpus_id: Mapped[int] = mapped_column(ForeignKey("corpus.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|running|done|failed|cancelled
    progress: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)     # {phase, done, total}
    sampling: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)     # {doc_ids, questions_per_doc}
    candidate_plan: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)  # per-stage candidate sets
    token_budget: Mapped[int | None] = mapped_column(default=None)
    tokens_spent: Mapped[int] = mapped_column(default=0)
    cost_estimate: Mapped[float | None] = mapped_column(default=None)
    cost_actual: Mapped[float | None] = mapped_column(default=None)
    results: Mapped[dict | None] = mapped_column(JSON_TYPE, default=None)  # greedy path + scores
    ephemeral_collections: Mapped[list] = mapped_column(JSON_TYPE, default=list)  # names to sweep
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class EvalQuestion(Base):
    __tablename__ = "eval_question"

    id: Mapped[int] = mapped_column(primary_key=True)
    eval_run_id: Mapped[int] = mapped_column(ForeignKey("eval_run.id"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("document.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer_chunk_refs: Mapped[list] = mapped_column(JSON_TYPE, default=list)  # ground-truth chunk ids
    source_chunk_text: Mapped[str] = mapped_column(Text)
    quality: Mapped[dict | None] = mapped_column(JSON_TYPE, default=None)     # critic outcome


class ConfigProposal(Base):
    __tablename__ = "config_proposal"

    id: Mapped[int] = mapped_column(primary_key=True)
    corpus_id: Mapped[int] = mapped_column(ForeignKey("corpus.id"), index=True)
    eval_run_id: Mapped[int] = mapped_column(ForeignKey("eval_run.id"), index=True)
    proposed_config: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    evidence: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)  # before/after, per-stage lifts, cost
    status: Mapped[str] = mapped_column(String(16), default="proposed")  # proposed|applied|dismissed
    approver: Mapped[str | None] = mapped_column(String(255), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class ResearchRun(Base):
    __tablename__ = "research_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    corpus_id: Mapped[int] = mapped_column(ForeignKey("corpus.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|running|done|failed|cancelled
    progress: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)      # {phase}
    prompt: Mapped[str] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)        # {source, document_ids, budget_chars, max_rounds, llm}
    report_markdown: Mapped[str | None] = mapped_column(Text, default=None)
    citations: Mapped[list] = mapped_column(JSON_TYPE, default=list)     # serialized research_agent Citations
    run_log: Mapped[list] = mapped_column(JSON_TYPE, default=list)       # every tool call + stop reason
    stop_reason: Mapped[str | None] = mapped_column(String(16), default=None)  # final|round_cap|no_tools_used|cancelled
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class AlchemyGoal(Base):
    """A standing, named autonomous goal over a corpus. The user refers to it
    by name (like documents/pipelines); runs version under it. spec is the raw
    authored format (stage A: {"goal": "..."}), compiled to sections by the
    alchemy package at run time."""
    __tablename__ = "alchemy_goal"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    corpus_id: Mapped[int] = mapped_column(ForeignKey("corpus.id"), index=True)
    goal_type: Mapped[str] = mapped_column(String(32))   # living-research (stage A); report (stage B)
    spec: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    coverage: Mapped[str] = mapped_column(String(16), default="search")  # search (stage A); full|exhaustive later
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AlchemyRun(Base):
    """One attempt to fill a goal, versioned WITHIN the goal (v1, v2, ...).
    based_on_version records which prior version a guidance rerun revised.
    usage is the token/call accounting dict (alchemy.Usage as a dict)."""
    __tablename__ = "alchemy_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("alchemy_goal.id"), index=True)
    version: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|running|done|failed|cancelled
    coverage: Mapped[str] = mapped_column(String(16), default="search")
    guidance: Mapped[str | None] = mapped_column(Text, default=None)
    based_on_version: Mapped[int | None] = mapped_column(default=None)
    progress: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)      # {phase}
    draft_markdown: Mapped[str | None] = mapped_column(Text, default=None)
    citations: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    run_log: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    sections: Mapped[list] = mapped_column(JSON_TYPE, default=list)          # per-section results (report goals): [{key,title,content,filled,note,confidence,stop_reason,llm_calls}]
    usage: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)         # {llm_calls, prompt_tokens, completion_tokens, total_tokens}
    ledger: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)         # coverage ledger dict (stage C): {mode,total_docs,consulted,from_prior,unconsulted,failures,complete,shortfall,summary}
    stop_reason: Mapped[str | None] = mapped_column(String(16), default=None)
    is_final: Mapped[bool] = mapped_column(default=False)
    config: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)        # {llm, budget_chars, max_rounds, max_llm_calls}
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


# Engine/session are process globals, configured once at startup (or per test).
engine = None
SessionLocal = None


def configure_engine(database_url: str):
    """Build the engine + session factory for this process."""
    global engine, SessionLocal
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    SessionLocal = sessionmaker(bind=engine)
    return engine


def create_all() -> None:
    if engine is None:
        raise RuntimeError("configure_engine() must be called before create_all()")
    Base.metadata.create_all(engine)
    _ensure_added_columns()


def _ensure_added_columns() -> None:
    """create_all() builds missing tables but never ALTERs existing ones, and we
    run no Alembic. Add columns introduced after a deploy so an existing database
    is upgraded in place without dropping data. Postgres only: sqlite always
    builds tables fresh above, so the column is already present there.
    Idempotent (ADD COLUMN IF NOT EXISTS)."""
    if engine.dialect.name != "postgresql":
        return
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE document ADD COLUMN IF NOT EXISTS "
            "progress JSONB NOT NULL DEFAULT '{}'::jsonb"))
        conn.execute(text(
            "ALTER TABLE extraction_comparison ADD COLUMN IF NOT EXISTS pages JSONB"))
        conn.execute(text(
            "ALTER TABLE document ADD COLUMN IF NOT EXISTS selected_pipeline_id INTEGER"))
        conn.execute(text(
            "ALTER TABLE pipeline ADD COLUMN IF NOT EXISTS "
            "progress JSONB NOT NULL DEFAULT '{}'::jsonb"))
        conn.execute(text(
            "ALTER TABLE llm_endpoint ADD COLUMN IF NOT EXISTS "
            "supports_text BOOLEAN NOT NULL DEFAULT true"))
        conn.execute(text(
            "ALTER TABLE llm_endpoint ADD COLUMN IF NOT EXISTS "
            "supports_vision BOOLEAN NOT NULL DEFAULT false"))
        conn.execute(text(
            "ALTER TABLE llm_endpoint ADD COLUMN IF NOT EXISTS "
            "is_vision_default BOOLEAN NOT NULL DEFAULT false"))
        conn.execute(text(
            "ALTER TABLE llm_endpoint ADD COLUMN IF NOT EXISTS "
            "api_flavor VARCHAR(16) NOT NULL DEFAULT 'chat'"))
        conn.execute(text(
            "ALTER TABLE document_corpus ADD COLUMN IF NOT EXISTS pipeline_id INTEGER"))
        # Carry existing single pins forward into the multi-select table (idempotent):
        # every old non-null pin becomes one selected pipeline for that (corpus, doc).
        conn.execute(text(
            "INSERT INTO document_corpus_pipeline (corpus_id, document_id, pipeline_id) "
            "SELECT corpus_id, document_id, pipeline_id FROM document_corpus "
            "WHERE pipeline_id IS NOT NULL ON CONFLICT DO NOTHING"))
        # Sweeper liveness columns (Task 6). The ALTER ... ADD COLUMN IF NOT EXISTS
        # migrates deployed Postgres in place with no data loss and no drop+recreate.
        # (create_all alone never ALTERs existing tables, but we run these ALTERs here
        # explicitly for exactly this reason.) Only a SQLite dev DB -- which this
        # function skips at the top -- would need a manual recreate if it predates
        # these columns.
        conn.execute(text(
            "ALTER TABLE document ADD COLUMN IF NOT EXISTS "
            "updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()"))
        conn.execute(text(
            "ALTER TABLE pipeline ADD COLUMN IF NOT EXISTS "
            "updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()"))
        conn.execute(text(
            "ALTER TABLE alchemy_run ADD COLUMN IF NOT EXISTS "
            "sections JSONB NOT NULL DEFAULT '[]'::jsonb"))
        conn.execute(text(
            "ALTER TABLE alchemy_run ADD COLUMN IF NOT EXISTS "
            "ledger JSONB NOT NULL DEFAULT '{}'::jsonb"))


def seed_llm_endpoints_from_env(settings) -> bool:
    """Seed one default endpoint from the index-LLM env, ONCE, when the registry
    is empty. After seeding, the table is the source of truth. Idempotent."""
    import os
    with SessionLocal() as session:
        if session.query(LlmEndpoint).count() > 0:
            return False
        if not settings.index_llm_provider or not settings.index_llm_model:
            return False
        key_var = "MADOSHO_LLM_API_KEY" if os.environ.get("MADOSHO_LLM_API_KEY") else None
        session.add(LlmEndpoint(
            name="default from env", provider=settings.index_llm_provider,
            model=settings.index_llm_model, api_base=settings.llm_api_base or "",
            key_env_var=key_var, is_default=True,
            supports_text=True, supports_vision=True, is_vision_default=True))
        session.commit()
        return True


def set_default_endpoint(session, endpoint_id: int) -> "LlmEndpoint":
    """Mark one endpoint default and clear the rest, in one transaction."""
    from sqlalchemy import update
    row = session.get(LlmEndpoint, endpoint_id)
    if row is None:
        raise ValueError(f"No LlmEndpoint with id={endpoint_id}")
    if not row.supports_text:
        raise ValueError(f"endpoint {endpoint_id} does not support text")
    session.execute(update(LlmEndpoint).values(is_default=False))
    row.is_default = True
    session.commit()
    return row


def set_vision_default_endpoint(session, endpoint_id: int) -> "LlmEndpoint":
    """Mark one vision-capable endpoint the vision default and clear the rest."""
    from sqlalchemy import update
    row = session.get(LlmEndpoint, endpoint_id)
    if row is None:
        raise ValueError(f"No LlmEndpoint with id={endpoint_id}")
    if not row.supports_vision:
        raise ValueError(f"endpoint {endpoint_id} does not support vision")
    session.execute(update(LlmEndpoint).values(is_vision_default=False))
    row.is_vision_default = True
    session.commit()
    return row


def get_session():
    """FastAPI dependency: yield a session per request."""
    with SessionLocal() as session:
        yield session
