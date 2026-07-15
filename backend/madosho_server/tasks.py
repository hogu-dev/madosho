from __future__ import annotations

import copy
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import procrastinate
import procrastinate.testing
from sqlalchemy import delete, select

from madosho.core.config import MadoshoConfig
from madosho.core.corpus import Corpus, open_corpus_from_config
from madosho.core.types import SourceFile
from madosho_server import db, extraction, membership, pipelines as pipelines_mod
from madosho_server.components import list_components
from madosho_server.eval import golden, planner, search, attribute, proposal
from madosho_server.eval import runner as eval_runner
from madosho_server.filestore import FileStore
from madosho_server.llm import complete
from madosho_server.progress import DbIngestReporter, count_pdf_pages
from madosho_server.executor import resolve_executor
from madosho_server.settings import Settings
from madosho_server.static_rater import rate_static
from madosho_server.traits import extract_traits

logger = logging.getLogger("madosho_server.worker")

# The connector is assigned per process at startup (control plane: a defer-only
# SyncPsycopgConnector; worker: an async PsycopgConnector). The InMemoryConnector
# default keeps imports cheap and lets fast tests run with no Postgres.
app = procrastinate.App(connector=procrastinate.testing.InMemoryConnector())


def use_connector(connector: procrastinate.BaseConnector) -> None:
    """Swap the queue connector for this process (persistently)."""
    app.connector = connector
    app.job_manager.connector = connector


def _dispatch(queue: str, name: str, kwargs: dict) -> None:
    """Single seam: run this job via the queue's configured backend."""
    resolve_executor(queue, Settings.from_env(), _IMPLS).run(name, kwargs)


# Process-level corpus cache: models load once per process, then stay warm.
# Safe without locking because the worker runs at concurrency=1.
# Maps corpus_id -> (config_hash, opened Corpus); evicts and reopens on hash
# change so Apply / PUT /config take effect without a process restart.
_CORPUS_CACHE: dict[int, tuple[str, Corpus]] = {}


def _config_hash(config: dict) -> str:
    return hashlib.sha256(
        json.dumps(config, sort_keys=True, default=str).encode()
    ).hexdigest()


def reset_corpus_cache() -> None:
    _CORPUS_CACHE.clear()


def _corpus_for(corpus_row: db.Corpus, corpora_dir: str) -> Corpus:
    h = _config_hash(corpus_row.config)
    entry = _CORPUS_CACHE.get(corpus_row.id)
    if entry is None or entry[0] != h:
        cfg = MadoshoConfig(**corpus_row.config)
        data_dir = Path(corpora_dir) / f"corpus-{corpus_row.id}"
        corpus = open_corpus_from_config(cfg, data_dir=data_dir)
        _CORPUS_CACHE[corpus_row.id] = (h, corpus)
    return _CORPUS_CACHE[corpus_row.id][1]


def rate_document(session, document_id: int) -> None:
    """Compute traits + the static cube for one indexed document. Idempotent:
    clears this document's prior static rows first. Caller commits."""
    doc = session.get(db.Document, document_id)
    if doc is None or not doc.artifacts:
        return
    doc.traits = extract_traits(doc.artifacts)
    # Scope to doc-level rows only (candidate_config IS NULL). Per-pipeline step
    # ratings carry candidate_config=pipeline.name and are managed separately by
    # pipelines.rate_pipeline_steps; deleting them here would wipe them on re-rate.
    session.execute(delete(db.TechniqueRating).where(
        db.TechniqueRating.document_id == document_id,
        db.TechniqueRating.candidate_config.is_(None),
        db.TechniqueRating.source == "static"))
    for row in rate_static(doc.traits):
        session.add(db.TechniqueRating(document_id=document_id, **row))


def _eval_questions_payload(rows: list[dict]) -> list[dict]:
    return [{"question": r["question"], "answer_chunk_refs": r["answer_chunk_refs"],
             "source_chunk_text": r["source_chunk_text"]} for r in rows]


def _is_cancelled(session, run_id: int) -> bool:
    # re-read from the DB so an external cancel (different session) is visible
    session.expire_all()
    run = session.get(db.EvalRun, run_id)
    return run is not None and run.status == "cancelled"


def _is_research_cancelled(session, run_id: int) -> bool:
    # re-read from the DB so an external cancel (different session) is visible
    session.expire_all()
    run = session.get(db.ResearchRun, run_id)
    return run is not None and run.status == "cancelled"


def _is_alchemy_cancelled(session, run_id: int) -> bool:
    # re-read from the DB so an external cancel (different session) is visible
    session.expire_all()
    run = session.get(db.AlchemyRun, run_id)
    return run is not None and run.status == "cancelled"


def _finish(session, run, status: str, error: str | None = None) -> None:
    run.status = status
    run.error = error
    run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
    session.commit()


def execute_run(session, eval_run_id: int, settings, *, llm,
                opener=None, list_registry=None, drop_collection=None) -> None:
    """Run the full eval pipeline for one eval_run. Injectable deps (llm, opener,
    list_registry, drop_collection) keep this unit-testable without models/Qdrant."""
    run = session.get(db.EvalRun, eval_run_id)
    if run is None:
        return
    corpus_row = session.get(db.Corpus, run.corpus_id)
    baseline = corpus_row.config
    registry = (list_registry or list_components)()
    opener = opener or eval_runner._default_opener(settings.corpora_dir, run.id)
    drop_collection = drop_collection or eval_runner._qdrant_dropper(
        settings.corpora_dir, run.id, baseline)

    run.status = "running"
    run.progress = {"phase": "golden", "done": 0, "total": 0}
    session.commit()

    docs = membership.member_documents(session, run.corpus_id, indexed_only=True)
    doc_payloads = [{"id": d.id, "content_hash": d.content_hash, "traits": d.traits or {},
                     "chunks": (d.artifacts or {}).get("chunks", [])} for d in docs]
    sampling = run.sampling or {}
    sr = None
    try:
        # 1. golden set (only LLM spend)
        rows = golden.build_golden_set(
            doc_payloads, n_docs=sampling.get("n_docs", len(doc_payloads)),
            per_doc=sampling.get("questions_per_doc", 3), llm=llm)
        for r in rows:
            session.add(db.EvalQuestion(eval_run_id=run.id, **r))
        run.tokens_spent = getattr(llm, "tokens", 0)
        run.progress = {"phase": "golden", "done": len(rows), "total": len(rows)}
        session.commit()
        if _is_cancelled(session, run.id):
            return _finish(session, run, "cancelled")
        if not rows:                                   # nothing to score
            run.results = {"note": "no golden questions generated"}
            return _finish(session, run, "done")

        questions = _eval_questions_payload(rows)
        plan = planner.build_plan(baseline, registry, traits={})

        # 2. trunk: parse once iff any ingest-side candidate needs re-chunk/re-embed
        needs_parse = any(c["kind"] == "ingest" for cands in plan.values() for c in cands)
        base_corpus = opener(baseline, None)
        parsed = {}
        if needs_parse:
            store = FileStore(settings.filestore_dir)
            for d in docs:
                sf = SourceFile(path=str(store.path_for(d.file_uri)),
                                content_hash=d.content_hash, mimetype=d.mimetype)
                parsed[d.content_hash] = base_corpus.parse_file(sf)

        sr = eval_runner.StageRunner(baseline, run.id, settings.corpora_dir, parsed,
                                     opener=opener, drop_collection=drop_collection)
        sr._built[eval_runner.ingest_prefix(baseline)] = base_corpus    # reuse the opened baseline

        run.progress = {"phase": "scan", "done": 0,
                        "total": sum(len(v) for v in plan.values())}
        session.commit()
        if _is_cancelled(session, run.id):
            return _finish(session, run, "cancelled")

        # 3. scan + greedy stack
        result = search.run_search(sr, plan, questions)
        if _is_cancelled(session, run.id):
            return _finish(session, run, "cancelled")

        # 4. write back: cube cells + proposal
        run.progress = {"phase": "writeback"}
        session.commit()
        cells = attribute.write_cube(session, run.corpus_id, run.id, result["scan"])
        proposal.build_proposal(session, run.corpus_id, run.id, baseline, result["greedy"])
        run.results = {"greedy": result["greedy"], "cells": cells,
                       "baseline": result["scan"]["baseline"]["post"]}
        run.ephemeral_collections = list(sr.ephemeral_collections)
        run.progress = {"phase": "done"}
        _finish(session, run, "done")
    except Exception as e:
        logger.exception("eval run %s failed", eval_run_id)
        session.rollback()
        run = session.get(db.EvalRun, eval_run_id)
        _finish(session, run, "failed", error=str(e))
    finally:
        if sr is not None:
            sr.cleanup()


def sweep_leaked_collections(session, drop_collection) -> int:
    """Backstop for crashes: drop ephemeral collections recorded on terminal runs.
    Idempotent (drop ignores missing collections)."""
    runs = session.scalars(select(db.EvalRun).where(
        db.EvalRun.status.in_(["done", "failed", "cancelled"]))).all()
    dropped = 0
    for run in runs:
        for name in (run.ephemeral_collections or []):
            try:
                drop_collection(name); dropped += 1
            except Exception:
                pass
    return dropped


def _with_collection(config: dict, collection: str) -> dict:
    """Return a deep copy of config with store.qdrant.collection set.
    Handles the case where store is a legacy string adapter name by replacing
    it with a dict before writing the collection key."""
    cfg = copy.deepcopy(config)
    ingest = cfg.setdefault("ingest", {})
    if not isinstance(ingest.get("store"), dict):
        ingest["store"] = {}
    ingest["store"].setdefault("qdrant", {})["collection"] = collection
    return cfg


def _pipeline_data_dir(corpora_dir: str, pipeline_id: int) -> Path:
    return Path(corpora_dir) / f"pipeline-{pipeline_id}"


def _chunker_llm_endpoint(config: dict | None) -> str | None:
    """The endpoint name a contextual chunker recipe asked for, if any. The
    chunker slot may be a bare name ("contextual") or the mapping form
    {"contextual": {"llm_endpoint": "my-gpu", ...}}; only the latter selects an
    endpoint. None -> let _index_llm fall back to the registry default."""
    ing = (config or {}).get("ingest", {})
    chunker = ing.get("chunker")
    if isinstance(chunker, dict):
        opts = next(iter(chunker.values()), None)
        if isinstance(opts, dict):
            return opts.get("llm_endpoint")
    return None


def _index_llm(settings, endpoint_name: str | None = None):
    """Index-time LLM for the contextual chunker. Resolves the endpoint the recipe
    named (by `endpoint_name`), else the registry's default row. Opens its own
    short session (builds are infrequent). Returns None when nothing resolves ->
    the contextual chunker raises ConfigError, surfacing the missing LLM clearly.
    A named-but-missing endpoint falls back to the default rather than failing the
    build mid-flight (the builder UI already validates an endpoint exists)."""
    from madosho_server.llm_endpoints import resolve_llm
    with db.SessionLocal() as session:
        row = None
        if endpoint_name:
            row = session.scalar(
                select(db.LlmEndpoint).where(db.LlmEndpoint.name == endpoint_name))
        call, _ = resolve_llm(session, settings, row)
    return call


def _parser_vision_endpoint(config: dict | None) -> str | None:
    """The vision endpoint name a vision-parser recipe asked for, if any. The
    parser slot may be a bare name ("vision") or the mapping form
    {"vision": {"vision_endpoint": "my-gpu", ...}}; only the latter selects an
    endpoint. None -> let _index_vision fall back to the vision-default."""
    ing = (config or {}).get("ingest", {})
    parser = ing.get("parser")
    if isinstance(parser, dict):
        opts = next(iter(parser.values()), None)
        if isinstance(opts, dict):
            return opts.get("vision_endpoint")
    return None


def _index_vision(settings, endpoint_name: str | None = None):
    """Index-time vision LLM for the vision parser. Resolves the endpoint the recipe
    named, else the registry's vision-default row. Returns None when nothing
    resolves -> the vision parser raises ConfigError, surfacing the missing endpoint.
    A named-but-missing endpoint falls back to the vision-default (the builder UI
    already validates a vision endpoint exists)."""
    from madosho_server.llm_endpoints import resolve_vision_client
    with db.SessionLocal() as session:
        row = None
        if endpoint_name:
            row = session.scalar(
                select(db.LlmEndpoint).where(db.LlmEndpoint.name == endpoint_name))
        call, _ = resolve_vision_client(session, settings, row)
    return call


def _open_pipeline_corpus(pipeline: db.Pipeline, corpora_dir: str) -> Corpus:
    """Open the kernel Corpus bound to a pipeline's own collection. Fresh per call
    in the build path (builds are infrequent; model-sharing cache is a deferred
    optimization). Patched in unit tests to avoid real models/Qdrant.

    Injects the index-time LLM (so a contextual chunker can situate chunks) and the
    index-time vision client (so a vision parser can transcribe page images) during
    the build. Settings are read here (not threaded through the 2-arg signature
    the unit-test patches rely on); the read is a cheap env-backed dataclass."""
    cfg = MadoshoConfig(**pipeline.config)
    settings = Settings.from_env()
    return open_corpus_from_config(
        cfg, data_dir=_pipeline_data_dir(corpora_dir, pipeline.id),
        llm=_index_llm(settings, _chunker_llm_endpoint(pipeline.config)),
        vision=_index_vision(settings, _parser_vision_endpoint(pipeline.config)))


def _pipeline_collection(pipeline_id: int) -> str:
    return f"madosho_p{pipeline_id}"


def _default_pipeline_name(session, doc: db.Document) -> str:
    """Per-document default name; document names already disambiguate it."""
    return pipelines_mod.default_pipeline_name(doc.filename)


def recipe_config(base: dict, *, parser: str | None = None,
                  chunker: str | None = None, embedder: str | None = None,
                  options: dict | None = None) -> dict:
    """Apply a 3-slot upload recipe (H6: parser/chunker/embedder) onto a base
    config. Only provided slots override; the reranker/query stack from `base` is
    kept. Any inherited store collection is stripped - it is stamped per-pipeline.

    `options` is an optional {slot_kind: {opt: val}} map. A slot with non-empty
    options is written as the ComponentRef mapping form `{name: {opts}}`; a slot
    without options stays a bare name string. Slot keys are the kernel kinds:
    'parser' / 'chunker' / 'embedder'."""
    cfg = copy.deepcopy(base)
    ing = cfg.setdefault("ingest", {})
    options = options or {}

    def _set(slot: str, name: str | None) -> None:
        if not name:
            return
        opts = options.get(slot)
        ing[slot] = {name: opts} if opts else name

    _set("parser", parser)
    _set("chunker", chunker)
    _set("embedder", embedder)
    store = ing.get("store")
    if isinstance(store, dict) and isinstance(store.get("qdrant"), dict):
        store["qdrant"].pop("collection", None)
    return cfg


def create_pipeline_from_config(session, doc: db.Document, config: dict, name: str,
                                *, is_default: bool = False) -> db.Pipeline:
    """Find-or-create a NAMED pipeline on a document from a full kernel config.
    Idempotent by (document_id, name): if the name is taken, return that pipeline
    unchanged (recipe slots are NEVER compared). Otherwise create a 'building'
    pipeline pointed at its own collection. Caller commits."""
    existing = session.scalar(select(db.Pipeline).where(
        db.Pipeline.document_id == doc.id, db.Pipeline.name == name))
    if existing is not None:
        return existing
    p = db.Pipeline(document_id=doc.id, name=name, config={}, slots={},
                    status="building", is_default=is_default)
    session.add(p)
    session.flush()                                  # assign p.id
    p.collection = _pipeline_collection(p.id)
    p.config = _with_collection(config, p.collection)
    p.slots = pipelines_mod.slots_from_config(p.config)
    session.flush()
    return p


def create_default_pipeline(session, corpus_row: db.Corpus, doc: db.Document) -> db.Pipeline:
    """The document's default (docling) pipeline, built from the corpus recipe.
    Thin wrapper over create_pipeline_from_config; kept for the upload-in-corpus
    caller. Idempotent: a doc that already has a default pipeline keeps it."""
    existing = session.scalar(select(db.Pipeline).where(
        db.Pipeline.document_id == doc.id, db.Pipeline.is_default.is_(True)))
    if existing is not None:
        return existing
    return create_pipeline_from_config(
        session, doc, corpus_row.config, _default_pipeline_name(session, doc),
        is_default=True)


def _build_into_pipeline(session, pipeline: db.Pipeline, settings, *,
                         reporter=None) -> None:
    """Build one pipeline: open its corpus, ingest the document's source into the
    pipeline's own collection, persist artifacts, mark indexed, rate the steps.
    Raises on failure (caller marks failed + drops the partial collection)."""
    doc = session.get(db.Document, pipeline.document_id)
    store = FileStore(settings.filestore_dir)
    sf = SourceFile(path=str(store.path_for(doc.file_uri)),
                    content_hash=doc.content_hash, mimetype=doc.mimetype)
    corpus = _open_pipeline_corpus(pipeline, settings.corpora_dir)
    if reporter is not None:
        ing = pipeline.config.get("ingest", {}) if pipeline.config else {}
        indexes = ", ".join(ing.get("indexes", []) or [])
        reporter.log(
            f"recipe: {ing.get('parser', '?')} -> {ing.get('chunker', '?')} -> "
            f"{ing.get('embedder', '?')}" + (f" [{indexes}]" if indexes else ""))
    artifacts = corpus.ingest_file(sf, reporter=reporter)
    pipeline.kernel_doc_id = artifacts.doc_id
    pipeline.artifacts = artifacts.model_dump(mode="json")
    pipeline.status = "indexed"
    pipeline.error = None
    pipelines_mod.rate_pipeline_steps(session, pipeline)


def _ingest_document_impl(document_id: int) -> None:
    settings = Settings.from_env()
    store = FileStore(settings.filestore_dir)
    with db.SessionLocal() as session:
        doc = session.get(db.Document, document_id)
        if doc is None:
            logger.warning("ingest_document: no document row %s", document_id)
            return
        doc.status = "indexing"
        session.commit()
        pipeline = None
        try:
            pipeline = session.scalar(select(db.Pipeline).where(
                db.Pipeline.document_id == doc.id, db.Pipeline.is_default.is_(True)))
            if pipeline is None:
                raise ValueError(f"document {document_id} has no default pipeline")
            pipeline.status = "building"
            pipeline.error = None
            session.commit()
            page_count = count_pdf_pages(store.path_for(doc.file_uri), doc.mimetype)
            # The Workbench build console reads the pipeline's progress (it's
            # pipeline-centric, like build_pipeline), so publish the live build
            # feed to the Pipeline row -- otherwise the FIRST upload's console
            # shows "waiting for the worker..." for the whole build. The document
            # only needs page_count for its header, so set that directly.
            doc.progress = {"page_count": page_count}
            session.commit()
            with DbIngestReporter(db.SessionLocal, pipeline.id,
                                  page_count=page_count, model=db.Pipeline) as reporter:
                _build_into_pipeline(session, pipeline, settings, reporter=reporter)
            doc.kernel_doc_id = pipeline.kernel_doc_id
            doc.artifacts = pipeline.artifacts
            doc.status = "indexed"
            doc.error = None
            try:
                rate_document(session, document_id)           # doc-level cube (unchanged)
            except Exception:
                logger.exception("rating failed for document %s (non-fatal)", document_id)
        except Exception as e:  # terminal failure: record it (no retry policy yet)
            logger.exception("ingest failed for document %s", document_id)
            doc.status = "failed"
            doc.error = str(e)
            if pipeline is not None:
                pipeline.status = "failed"
                pipeline.error = str(e)
                try:                                # discard the partial collection
                    eval_runner._qdrant_dropper(
                        settings.corpora_dir, 0, pipeline.config)(pipeline.collection)
                except Exception:
                    pass
        session.commit()


@app.task(queue="ingest", name="ingest_document")
def ingest_document(document_id: int) -> None:
    _dispatch("ingest", "ingest_document", {"document_id": document_id})


def _delete_document_artifacts_impl(collections: list[str], file_uri: str) -> None:
    """Async cleanup after a Document row is deleted: drop each of its pipelines'
    Qdrant collections (one document per collection, so a whole-collection drop is
    right) and unlink its file blob if no surviving Document points at it.
    Best-effort and idempotent."""
    settings = Settings.from_env()
    with db.SessionLocal() as session:
        drop = eval_runner._qdrant_dropper(
            settings.corpora_dir, 0,
            {"ingest": {"store": {"qdrant": {"url": settings.qdrant_url}}}})
        for name in (collections or []):
            try:
                drop(name)
            except Exception:
                logger.exception("failed to drop pipeline collection %s", name)
        # The blob is content-addressed and shared across corpora (the store dedups
        # by hash), so only unlink it when no surviving Document row points at it.
        still_used = session.scalar(
            select(db.Document).where(db.Document.file_uri == file_uri))
        if still_used is None:
            path = FileStore(settings.filestore_dir).path_for(file_uri)
            try:
                path.unlink(missing_ok=True)
                parent = path.parent
                if parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()      # remove the now-empty <content_hash>/ dir
            except OSError:
                logger.exception("failed to remove blob %s", file_uri)


@app.task(queue="ingest", name="delete_document_artifacts")
def delete_document_artifacts(collections: list[str], file_uri: str) -> None:
    _dispatch("ingest", "delete_document_artifacts",
              {"collections": collections, "file_uri": file_uri})


def _run_extraction_comparison_impl(document_id: int) -> None:
    settings = Settings.from_env()
    with db.SessionLocal() as session:
        extraction.run_extraction_comparison(session, document_id, settings)
        session.commit()


@app.task(queue="ratings", name="run_extraction_comparison")
def run_extraction_comparison_task(document_id: int) -> None:
    _dispatch("ratings", "run_extraction_comparison", {"document_id": document_id})


def _eval_llm(settings, provider, model):
    """The pluggable golden-set LLM (no default provider; the wizard must set one).
    Wraps llm.complete and accumulates token usage for cost tracking."""
    class _Counter:
        def __init__(self):
            self.tokens = 0
            self.provider = provider
            self.model = model

        def __call__(self, prompt: str) -> str:
            resp = complete(messages=[{"role": "user", "content": prompt}],
                            provider=provider, model=model, settings=settings)
            usage = getattr(resp, "usage", None)
            if usage is not None:
                self.tokens += int(getattr(usage, "total_tokens", 0) or 0)
            return resp.choices[0].message.content

    return _Counter()


def _run_eval_impl(eval_run_id: int) -> None:
    settings = Settings.from_env()
    with db.SessionLocal() as session:
        run = session.get(db.EvalRun, eval_run_id)
        if run is None:
            logger.warning("run_eval: no eval_run %s", eval_run_id)
            return
        cfg = (run.sampling or {}).get("llm", {})
        provider, model = cfg.get("provider"), cfg.get("model")
        eval_settings = settings
        if not provider or not model:
            from madosho_server.llm_endpoints import resolve_llm, endpoint_creds
            _, row = resolve_llm(session, settings)
            if row is not None:
                provider, model = row.provider, row.model
                eval_settings = endpoint_creds(settings, row)
        llm = _eval_llm(eval_settings, provider, model)
        execute_run(session, eval_run_id, settings, llm=llm)


@app.task(queue="eval", name="run_eval")
def run_eval(eval_run_id: int) -> None:
    _dispatch("eval", "run_eval", {"eval_run_id": eval_run_id})


def _run_research_impl(research_run_id: int) -> None:
    from madosho_server import research   # lazy: research.py imports tasks._finish
    settings = Settings.from_env()
    with db.SessionLocal() as session:
        run = session.get(db.ResearchRun, research_run_id)
        if run is None:
            logger.warning("run_research: no research_run %s", research_run_id)
            return
        research.execute_research(session, research_run_id, settings)


@app.task(queue="research", name="run_research")
def run_research(research_run_id: int) -> None:
    _dispatch("research", "run_research", {"research_run_id": research_run_id})


def _run_alchemy_impl(alchemy_run_id: int) -> None:
    from madosho_server import alchemy_exec   # lazy: alchemy_exec imports tasks._finish
    settings = Settings.from_env()
    with db.SessionLocal() as session:
        run = session.get(db.AlchemyRun, alchemy_run_id)
        if run is None:
            logger.warning("run_alchemy: no alchemy_run %s", alchemy_run_id)
            return
        alchemy_exec.execute_alchemy_run(session, alchemy_run_id, settings)


@app.task(queue="alchemy", name="run_alchemy")
def run_alchemy(alchemy_run_id: int) -> None:
    _dispatch("alchemy", "run_alchemy", {"alchemy_run_id": alchemy_run_id})


def _build_pipeline_impl(pipeline_id: int) -> None:
    """Build one already-created Pipeline row into its own collection. On failure,
    mark it failed and drop the partial collection (same discipline as ingest)."""
    settings = Settings.from_env()
    with db.SessionLocal() as session:
        pipeline = session.get(db.Pipeline, pipeline_id)
        if pipeline is None:
            logger.warning("build_pipeline: no pipeline row %s", pipeline_id)
            return
        try:
            # Publish a live build console to pipeline.progress (same reporter the
            # original ingest uses, just pointed at the Pipeline row). The reporter
            # owns `progress` via its own sessions; this main session writes only
            # status/artifacts, so the two non-overlapping UPDATEs never collide.
            doc = session.get(db.Document, pipeline.document_id)
            store = FileStore(settings.filestore_dir)
            page_count = (count_pdf_pages(store.path_for(doc.file_uri), doc.mimetype)
                          if doc is not None else None)
            with DbIngestReporter(db.SessionLocal, pipeline_id,
                                  page_count=page_count, model=db.Pipeline) as reporter:
                _build_into_pipeline(session, pipeline, settings, reporter=reporter)
                session.commit()
        except Exception as e:
            logger.exception("build_pipeline failed for pipeline %s", pipeline_id)
            session.rollback()
            pipeline = session.get(db.Pipeline, pipeline_id)
            if pipeline is not None:
                pipeline.status = "failed"
                pipeline.error = str(e)
                try:
                    eval_runner._qdrant_dropper(
                        settings.corpora_dir, 0, pipeline.config)(pipeline.collection)
                except Exception:
                    pass
            session.commit()


@app.task(queue="ingest", name="build_pipeline")
def build_pipeline(pipeline_id: int) -> None:
    _dispatch("ingest", "build_pipeline", {"pipeline_id": pipeline_id})


# -- KB semantic index -------------------------------------------------------
# Page-level embeddings for KB pages, kept in per-KB qdrant collections. Runs
# on the worker (the app process loads no local model); jobs ride the "ingest"
# queue, which the worker already drains inproc with the embedder warm. The
# embedder cache + store factory are shared with the query plane in kb_index.
def _kb_embedder():
    from madosho_server import kb_index
    return kb_index.get_embedder()


def _kb_store(settings, kb_id: int):
    from madosho_server import kb_index
    return kb_index.open_store(settings.qdrant_url, kb_id)


def _kb_pages(settings, kb_id: int) -> list[dict]:
    from madosho_server import kb_store
    root = kb_store.kb_root(settings.kb_dir, kb_id)
    pages: list[dict] = []
    for summ in kb_store.list_pages(root):
        page = kb_store.get_page(root, summ["slug"])
        if page is not None:
            pages.append(page)
    return pages


def _index_kb_page_impl(kb_id: int, slug: str) -> None:
    from madosho_server import kb_index, kb_store
    settings = Settings.from_env()
    page = kb_store.get_page(kb_store.kb_root(settings.kb_dir, kb_id), slug)
    if page is None:
        logger.warning("index_kb_page: no page %s in kb %s", slug, kb_id)
        return
    kb_index.index_page(_kb_store(settings, kb_id), _kb_embedder(), kb_id, page)


def _remove_kb_page_impl(kb_id: int, slug: str) -> None:
    from madosho_server import kb_index
    kb_index.remove_page(_kb_store(Settings.from_env(), kb_id), slug)


def _reindex_kb_impl(kb_id: int) -> None:
    from madosho_server import kb_index
    settings = Settings.from_env()
    n = kb_index.reindex(_kb_store(settings, kb_id), _kb_embedder(),
                         kb_id, _kb_pages(settings, kb_id))
    logger.info("reindex_kb: embedded %s page(s) for kb %s", n, kb_id)


def _drop_kb_index_impl(kb_id: int) -> None:
    from madosho_server import kb_index
    store = _kb_store(Settings.from_env(), kb_id)
    coll = kb_index.kb_collection(kb_id)
    try:
        if store.native.collection_exists(coll):
            store.native.delete_collection(coll)
    except Exception:
        logger.exception("drop_kb_index: failed to drop %s", coll)


@app.task(queue="ingest", name="index_kb_page")
def index_kb_page(kb_id: int, slug: str) -> None:
    _dispatch("ingest", "index_kb_page", {"kb_id": kb_id, "slug": slug})


@app.task(queue="ingest", name="remove_kb_page")
def remove_kb_page(kb_id: int, slug: str) -> None:
    _dispatch("ingest", "remove_kb_page", {"kb_id": kb_id, "slug": slug})


@app.task(queue="ingest", name="reindex_kb")
def reindex_kb(kb_id: int) -> None:
    _dispatch("ingest", "reindex_kb", {"kb_id": kb_id})


@app.task(queue="ingest", name="drop_kb_index")
def drop_kb_index(kb_id: int) -> None:
    _dispatch("ingest", "drop_kb_index", {"kb_id": kb_id})


_IMPLS = {
    "ingest_document": _ingest_document_impl,
    "delete_document_artifacts": _delete_document_artifacts_impl,
    "run_extraction_comparison": _run_extraction_comparison_impl,
    "run_eval": _run_eval_impl,
    "run_research": _run_research_impl,
    "run_alchemy": _run_alchemy_impl,
    "build_pipeline": _build_pipeline_impl,
    "index_kb_page": _index_kb_page_impl,
    "remove_kb_page": _remove_kb_page_impl,
    "reindex_kb": _reindex_kb_impl,
    "drop_kb_index": _drop_kb_index_impl,
}


def _noop_impl() -> None:
    return None


def _sleep_forever_impl() -> None:
    import time
    while True:
        time.sleep(1)


_IMPLS["noop"] = _noop_impl
_IMPLS["sleep_forever"] = _sleep_forever_impl
