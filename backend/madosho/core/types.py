from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

Vector = list[float]
MultiVector = list[Vector]   # one entry per token/patch vector (late interaction)


class BlockKind(StrEnum):
    TEXT = "text"
    HEADING = "heading"
    TABLE = "table"
    FIGURE = "figure"


class Provenance(BaseModel):
    source: str
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None


class Block(BaseModel):
    kind: BlockKind
    content: str
    provenance: Provenance


class SourceFile(BaseModel):
    path: str
    mimetype: str
    content_hash: str


class Document(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    doc_id: str
    source: SourceFile
    blocks: list[Block]
    # Parser-native payload (e.g. a DoclingDocument) for chunkers that work on
    # the original structure; never serialized.
    native: Any = Field(default=None, exclude=True)


class Chunk(BaseModel):
    id: str
    doc_id: str
    text: str
    context_prefix: str = ""
    position: int = 0
    page: int | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @property
    def embed_text(self) -> str:
        return f"{self.context_prefix}\n{self.text}" if self.context_prefix else self.text


class IngestArtifacts(BaseModel):
    """What a single-document ingest produced, surfaced for inspection/persistence.

    Additive return of `Corpus.ingest_file`. `blocks` are the parser's original
    blocks (tables included) with full `Provenance` — the `bbox` slot reserves room
    for Level-3 source highlighting without a later re-plumb.
    """

    doc_id: str
    chunks: list[Chunk] = Field(default_factory=list)
    blocks: list[Block] = Field(default_factory=list)


class EmbeddedChunk(BaseModel):
    chunk: Chunk
    vectors: dict[str, Vector]
    # Late-interaction payloads (e.g. ColBERT token vectors). Stores without
    # supports_multivector ignore this field.
    multivectors: dict[str, MultiVector] = Field(default_factory=dict)


def display_source(raw: str | None) -> str | None:
    """The human-facing label for a chunk's source.

    The stored source is the full filestore path (e.g.
    /data/filestore/<hash>/contract.pdf). Keep that full value in
    chunk.metadata for provenance, but every *display* of it — the shim's
    Sources footer, the in-prompt context blocks, the serialized `source`
    field, the CLI, Scrying, Research — wants just the filename. Deriving the
    basename here, at the single point the label is built, fixes it for every
    consumer at once. Filestore paths
    are always '/'-joined, so a plain rsplit is enough; None passes through.
    """
    if not raw:
        return raw
    return raw.rsplit("/", 1)[-1] or raw


class Hit(BaseModel):
    """A scored retrieval result. model_copy(update=...) shares `chunk` by reference — treat chunks as read-only."""

    chunk_id: str
    score: float
    source_index: str  # "bm25" | "dense" | ...
    chunk: Chunk

    @property
    def text(self) -> str:
        return self.chunk.text

    @property
    def citation(self) -> str:
        src = display_source(self.chunk.metadata.get("source")) or self.chunk.doc_id
        return f"{src} p.{self.chunk.page}" if self.chunk.page is not None else src


class Filters(BaseModel):
    equals: dict[str, str | int | float] = Field(default_factory=dict)
    any_of: dict[str, list[str | int | float]] = Field(default_factory=dict)
    ranges: dict[str, tuple[float | int, float | int]] = Field(default_factory=dict)


class IndexSpec(BaseModel):
    indexes: list[str] = Field(default_factory=lambda: ["bm25", "dense"])
    vectors: dict[str, int] = Field(default_factory=dict)  # name -> dims
    multivectors: dict[str, int] = Field(default_factory=dict)  # name -> per-vector dims (MaxSim)


class FileError(BaseModel):
    path: str
    error: str


class IngestReport(BaseModel):
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    seconds: float = 0.0
    errors: list[FileError] = Field(default_factory=list)

    def add_failure(self, path: str, error: str) -> None:
        self.failed += 1
        self.errors.append(FileError(path=path, error=error))


@dataclass
class TraceEntry:
    operator: str
    params: dict[str, Any]
    added: int
    seconds: float


@dataclass
class QueryContext:
    query: str
    pools: list[list[Hit]] = field(default_factory=list)
    hits: list[Hit] = field(default_factory=list)
    trace: list[TraceEntry] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
    _query_vector: Vector | None = field(default=None, repr=False, init=False)

    def query_vector(self, embedder) -> Vector:
        if self._query_vector is None:
            self._query_vector = embedder.embed([self.query])[0]
        return self._query_vector

    def record(self, operator: str, params: dict[str, Any], added: int, started: float) -> None:
        self.trace.append(TraceEntry(operator=operator, params=params,
                                     added=added, seconds=time.monotonic() - started))
