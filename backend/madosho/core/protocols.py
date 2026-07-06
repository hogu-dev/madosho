from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from madosho.core.meta import ComponentMeta, StoreCapabilities
from madosho.core.types import (
    Chunk, Document, EmbeddedChunk, Filters, Hit, IndexSpec, QueryContext,
    SourceFile, Vector,
)

T = TypeVar("T")


@runtime_checkable
class LlmClient(Protocol):
    """Minimal LLM seam the kernel can call at index time. A contextual chunker,
    for example, calls it to situate a chunk within its document. Deliberately
    provider-agnostic: the service injects a concrete client already bound to the
    configured provider/model (mirrors the eval golden-set llm); library/CLI ingest
    leaves it None. Takes a prompt, returns the completion text."""
    def __call__(self, prompt: str) -> str: ...


@runtime_checkable
class VisionClient(Protocol):
    """Multimodal index-time seam: like LlmClient but the call also carries one or
    more page images. A vision parser rasterizes each PDF page (or reads a directly
    uploaded image) and calls this to transcribe it. Images are PNG bytes -- the
    kernel normalizes whatever it has to PNG so this contract is one type; the
    service-injected client base64-encodes them into provider image messages
    (those wire details stay service-side). Provider-agnostic like LlmClient: the
    service binds a client to the configured vision endpoint; library/CLI ingest
    leaves it None and a vision parser then fails clearly. Returns the model text."""
    def __call__(self, prompt: str, images: list[bytes]) -> str: ...


@dataclass
class RuntimeContext:
    """Infrastructure the kernel injects into every component (spec §5.2.3)."""

    corpus: str
    data_dir: Path          # per-corpus working dir (.madosho/<corpus>/)
    cache_dir: Path | None  # model/download cache override; None = library default (HF shared cache)
    logger: logging.Logger
    device: str = "cpu"
    settings: dict[str, Any] = field(default_factory=dict)
    # Optional index-time LLM (e.g. for a contextual chunker). None unless a
    # provider is wired in; components that need it must fail clearly when absent.
    llm: LlmClient | None = None
    # Optional index-time vision LLM (e.g. for a vision parser that transcribes
    # rendered page images). None unless a vision endpoint is wired in; components
    # that need it must fail clearly when absent. Injected like `llm`.
    vision: VisionClient | None = None
    # Optional index-time embedder (e.g. for a semantic chunker that detects
    # topic shifts by embedding sentences). None unless the kernel wires the
    # pipeline's resolved embedder in; components that need it must fail clearly
    # when absent. Set by _build_corpus before the chunker is resolved.
    embedder: "Embedder | None" = None


class ComponentBase:
    """Optional convenience base: meta from class attr META, isinstance-based
    typed extensions, native=None. Adapters may use it; Protocols don't require it."""

    META: ComponentMeta

    @property
    def meta(self) -> ComponentMeta:
        return self.META

    def extension(self, iface: type[T]) -> T | None:
        return self if isinstance(self, iface) else None

    @property
    def native(self) -> Any:
        return None


@runtime_checkable
class IngestReporter(Protocol):
    """Optional progress sink the kernel calls while ingesting one file. The
    service injects a reporter that writes phase/log to the document row so the
    UI can poll it; library/CLI ingest passes none and stays silent. `phase`
    names a pipeline seam ("parsing" -> "chunking" -> "embedding" -> "storing");
    `log` is a free-form milestone line for a console view."""
    def phase(self, name: str) -> None: ...
    def log(self, message: str) -> None: ...


@runtime_checkable
class Parser(Protocol):
    meta: ComponentMeta
    def supports(self, file: SourceFile) -> bool: ...
    def parse(self, file: SourceFile) -> Document: ...


@runtime_checkable
class Chunker(Protocol):
    meta: ComponentMeta
    def chunk(self, doc: Document) -> list[Chunk]: ...


@runtime_checkable
class Embedder(Protocol):
    meta: ComponentMeta
    dims: int
    def embed(self, texts: list[str]) -> list[Vector]: ...


@runtime_checkable
class Store(Protocol):
    meta: ComponentMeta
    capabilities: StoreCapabilities
    def ensure_schema(self, spec: IndexSpec) -> None: ...
    def upsert(self, chunks: list[EmbeddedChunk]) -> None: ...
    def delete(self, doc_ids: list[str]) -> None: ...
    def keyword_search(self, query: str, k: int, filters: Filters | None = None) -> list[Hit]: ...
    def semantic_search(self, vector: Vector, k: int, filters: Filters | None = None) -> list[Hit]: ...
    def read(self, chunk_ids: list[str], window: int = 0) -> list[Chunk]: ...
    def extension(self, iface: type[T]) -> T | None: ...


@runtime_checkable
class MultiVectorSearch(Protocol):
    """Optional Store extension (kernel spec §5.2): late-interaction / MaxSim
    retrieval over a named multivector index declared in IndexSpec.multivectors.
    Vectors arrive at upsert time on EmbeddedChunk.multivectors; this extension
    only adds the query side. Discover with store.extension(MultiVectorSearch).
    An empty vectors list returns no hits."""

    def multivector_search(self, name: str, vectors: list[Vector], k: int,
                           filters: Filters | None = None) -> list[Hit]: ...


@runtime_checkable
class Reranker(Protocol):
    meta: ComponentMeta
    def rerank(self, query: str, hits: list[Hit], top_k: int) -> list[Hit]: ...


@dataclass
class OperatorDeps:
    store: Store
    embedder: Embedder
    reranker_for: Callable[[str], Reranker]   # name -> resolved Reranker (pre-validated at open())
    runtime: RuntimeContext


@runtime_checkable
class Operator(Protocol):
    meta: ComponentMeta
    name: str
    params_schema: type[BaseModel]
    def run(self, ctx: QueryContext, deps: OperatorDeps) -> QueryContext: ...
