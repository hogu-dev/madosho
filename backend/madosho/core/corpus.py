from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import time
from pathlib import Path

from madosho.core.config import MadoshoConfig, load_config
from madosho.core.errors import MadoshoError
from madosho.core.hooks import ResolutionContext
from madosho.core.meta import ComponentKind
from madosho.core.protocols import (
    IngestReporter, LlmClient, OperatorDeps, RuntimeContext, VisionClient,
)
from madosho.core.registry import Registry
from madosho.core.types import (
    Document, EmbeddedChunk, Hit, IngestArtifacts, IndexSpec, IngestReport, QueryContext,
    SourceFile,
)


class _NullReporter:
    """No-op IngestReporter: the default so non-service ingest stays silent."""
    def phase(self, name: str) -> None: ...
    def log(self, message: str) -> None: ...


_NULL_REPORTER = _NullReporter()


def open_corpus(config_path: str | Path, registry: Registry | None = None) -> "Corpus":
    """Resolve and validate everything up front (spec §8/§10: fail fast)."""
    cfg = load_config(config_path)
    # state lives next to madosho.yaml, independent of the process cwd
    state_root = (cfg.config_path.parent if cfg.config_path else Path(".")) / ".madosho"
    return _build_corpus(cfg, data_dir=state_root / cfg.corpus, registry=registry)


def open_corpus_from_config(cfg: MadoshoConfig, data_dir: str | Path,
                            registry: Registry | None = None,
                            llm: "LlmClient | None" = None,
                            vision: "VisionClient | None" = None) -> "Corpus":
    """Open a corpus from an already-built config object + an explicit state dir.

    The service holds each corpus's recipe as data (not a madosho.yaml on disk)
    and owns where state lives. Library/CLI users keep using open_corpus().

    `llm` is an optional index-time LLM injected onto the RuntimeContext (e.g. for
    a contextual chunker); `vision` is the multimodal counterpart (e.g. for a
    vision parser). The service wires these from its configured endpoints;
    library/CLI ingest leaves them None."""
    return _build_corpus(cfg, data_dir=Path(data_dir), registry=registry,
                         llm=llm, vision=vision)


def _build_corpus(cfg: MadoshoConfig, data_dir: Path,
                  registry: Registry | None = None,
                  llm: "LlmClient | None" = None,
                  vision: "VisionClient | None" = None) -> "Corpus":
    registry = registry or Registry()
    registry.discover_entry_points()

    runtime = RuntimeContext(
        corpus=cfg.corpus,
        data_dir=data_dir,
        # None -> model adapters fall through to the shared HF default cache;
        # a per-corpus cache would re-download ~600 MB of models per project
        cache_dir=None,
        logger=logging.getLogger(f"madosho.{cfg.corpus}"),
        llm=llm,
        vision=vision,
    )
    runtime.data_dir.mkdir(parents=True, exist_ok=True)
    rctx = ResolutionContext(
        corpus=cfg.corpus,
        config_path=str(cfg.config_path) if cfg.config_path else None,
    )

    def resolve(kind: ComponentKind, ref):
        return registry.resolve(kind, ref.name, ref.options, runtime, rctx)

    parser = resolve(ComponentKind.PARSER, cfg.ingest.parser)
    # Resolve the embedder before the chunker and expose it on the runtime, so a
    # semantic chunker (which embeds sentences to find topic boundaries) can reach
    # the pipeline's embedder. The embedder needs no embedder itself, so resolving
    # it first is safe. `runtime` is the shared context already handed to every
    # resolve() call.
    embedder = resolve(ComponentKind.EMBEDDER, cfg.ingest.embedder)
    runtime.embedder = embedder
    chunker = resolve(ComponentKind.CHUNKER, cfg.ingest.chunker)
    store = resolve(ComponentKind.STORE, cfg.ingest.store)
    operators = [resolve(ComponentKind.OPERATOR, step) for step in cfg.query]

    # Pre-resolve every reranker named by a rerank step: fail at open(), not mid-query.
    rerankers = {
        step.options["model"]: registry.resolve(
            ComponentKind.RERANKER, step.options["model"], {}, runtime, rctx)
        for step in cfg.query
        if step.name == "rerank" and "model" in step.options
    }

    store.ensure_schema(IndexSpec(indexes=cfg.ingest.indexes,
                                  vectors={"dense": embedder.dims}))
    return Corpus(cfg, runtime, parser, chunker, embedder, store, operators, rerankers)


class Corpus:
    def __init__(self, cfg: MadoshoConfig, runtime: RuntimeContext,
                 parser, chunker, embedder, store, operators, rerankers):
        self.name = cfg.corpus
        self._cfg = cfg
        self._runtime = runtime
        self._parser = parser
        self._chunker = chunker
        self._embedder = embedder
        self._store = store
        self._operators = operators
        def reranker_for(name: str):
            try:
                return rerankers[name]
            except KeyError:
                raise MadoshoError(
                    f"reranker '{name}' was not pre-resolved at open(); "
                    f"available: {sorted(rerankers) or 'none'}") from None

        self._deps = OperatorDeps(store=store, embedder=embedder,
                                  reranker_for=reranker_for, runtime=runtime)

    # -- ingest ------------------------------------------------------------

    @property
    def _manifest_path(self) -> Path:
        return self._runtime.data_dir / "manifest.json"

    def _load_manifest(self) -> dict[str, str]:
        if self._manifest_path.exists():
            try:
                return json.loads(self._manifest_path.read_text())
            except json.JSONDecodeError as e:
                raise MadoshoError(
                    f"ingest manifest {self._manifest_path} is corrupt ({e}); "
                    f"delete it to re-ingest from scratch") from e
        return {}

    @property
    def store(self):
        """Read-only access to the resolved store (F needs the native client to
        drop ephemeral eval collections; never mutate the store through this)."""
        return self._store

    def parse_file(self, sf: SourceFile,
                   reporter: IngestReporter | None = None) -> Document:
        """The expensive, extraction-only step. F caches this so OCR/parse runs
        once per document even when downstream stages are swept. `reporter` is an
        optional progress sink (the service's UI feed); None = silent."""
        reporter = reporter or _NULL_REPORTER
        reporter.phase("parsing")
        reporter.log(f"{self._parser.meta.name}: extracting text & layout")
        doc = self._parser.parse(sf)
        pages = len({b.provenance.page for b in doc.blocks if b.provenance.page is not None})
        reporter.log(f"parsed {pages} page(s), {len(doc.blocks)} block(s)" if pages
                     else f"parsed {len(doc.blocks)} block(s)")
        return doc

    def index_document(self, doc: Document,
                       reporter: IngestReporter | None = None) -> IngestArtifacts:
        """Chunk -> embed -> store a pre-parsed document. Splitting this out of
        ingest_file lets F rebuild only the stages downstream of a change while
        reusing the cached parse."""
        reporter = reporter or _NULL_REPORTER
        reporter.phase("chunking")
        reporter.log(f"{self._chunker.meta.name}: splitting {len(doc.blocks)} block(s)")
        chunks = self._chunker.chunk(doc)
        if not chunks:
            self._runtime.logger.warning(
                "ingest produced 0 chunks for %s (empty parse? scanned PDF "
                "without OCR?) — file is recorded as processed", doc.source.path)
        reporter.log(f"produced {len(chunks)} chunk(s)")
        reporter.phase("embedding")
        reporter.log(f"{self._embedder.meta.name}: embedding {len(chunks)} chunk(s), dim {self._embedder.dims}")
        vectors = self._embedder.embed([c.embed_text for c in chunks])
        reporter.phase("storing")
        reporter.log(f"{self._store.meta.name}: upserting {len(chunks)} vector(s)")
        self._store.delete([doc.doc_id])   # changed file: replace its chunks
        self._store.upsert([EmbeddedChunk(chunk=c, vectors={"dense": v})
                            for c, v in zip(chunks, vectors)])
        reporter.log("stored")
        return IngestArtifacts(doc_id=doc.doc_id, chunks=chunks, blocks=doc.blocks)

    def delete_document(self, doc_id: str) -> None:
        """Drop one document's chunks from the store — the inverse of the store
        write index_document does. The service's delete path calls this so a
        removed document leaves no orphan chunks polluting retrieval. We route
        through the kernel (not the read-only `store` property) so callers don't
        reach past the abstraction, and a future store needing extra teardown has
        one place to add it. Idempotent: deleting an unknown doc_id is a no-op the
        Store absorbs."""
        self._store.delete([doc_id])

    def ingest_file(self, sf: SourceFile,
                    reporter: IngestReporter | None = None) -> IngestArtifacts:
        """Ingest exactly one file: parse -> chunk -> embed -> store.

        Raises on failure (the caller owns idempotency and bookkeeping).
        Returns the parsed artifacts (chunks + original blocks) it indexed, so
        callers can persist/inspect them. Assumes the parser supports the file —
        callers that batch should gate on parser.supports() first."""
        return self.index_document(self.parse_file(sf, reporter), reporter)

    def ingest(self) -> IngestReport:
        started = time.monotonic()
        if self._cfg.source is None:
            raise MadoshoError(
                "corpus has no `source` directory; use ingest_file() for "
                "single files (e.g. the service ingest path)")
        source = Path(self._cfg.source)
        if not source.is_dir():
            raise MadoshoError(
                f"corpus source directory does not exist: {source}")
        report = IngestReport()
        manifest = self._load_manifest()
        # v0 limitation (documented): files deleted or renamed since the last
        # ingest are not reconciled — their chunks/manifest entries linger.
        for path in sorted(p for p in source.rglob("*") if p.is_file()):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            sf = SourceFile(path=str(path), content_hash=digest,
                            mimetype=mimetypes.guess_type(path)[0] or "application/octet-stream")
            if manifest.get(sf.path) == digest:
                report.skipped += 1
                continue
            try:
                if not self._parser.supports(sf):
                    report.skipped += 1
                    continue
                self.ingest_file(sf)
                manifest[sf.path] = digest          # only marked done on full success
                report.processed += 1
            except Exception as e:                  # fail soft: file-level isolation
                self._runtime.logger.warning("ingest failed for %s: %s", sf.path, e)
                report.add_failure(sf.path, str(e))
        tmp = self._manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(manifest, indent=0))
        os.replace(tmp, self._manifest_path)   # atomic: never a half-written manifest
        report.seconds = time.monotonic() - started
        return report

    # -- query -------------------------------------------------------------

    def query(self, text: str) -> list[Hit]:
        ctx = QueryContext(query=text)
        for op in self._operators:
            ctx = op.run(ctx, self._deps)
        return ctx.hits
