from __future__ import annotations

import hashlib
import logging
import math
from pathlib import Path

from pydantic import BaseModel

from madosho.core.errors import MadoshoError
from madosho.core.meta import (
    ComponentKind, ComponentMeta, Hardware, OriginTier, StoreCapabilities,
)
from madosho.core.protocols import ComponentBase, RuntimeContext
from madosho.core.types import (
    Block, BlockKind, Chunk, Document, EmbeddedChunk, Filters, Hit,
    IndexSpec, Provenance, SourceFile, Vector,
)


def _meta(name: str, kind: ComponentKind) -> ComponentMeta:
    return ComponentMeta(name=name, kind=kind, version="0.1.0", license="Apache-2.0",
                         org="madosho", org_country="US",
                         origin_tier=OriginTier.US_SRC, hardware=Hardware.CPU)


def _test_runtime() -> RuntimeContext:
    tmp = Path("/tmp/madosho-fakes")
    return RuntimeContext(corpus="test", data_dir=tmp, cache_dir=tmp,
                          logger=logging.getLogger("madosho.fakes"))


class _Fake(ComponentBase):
    class Options(BaseModel):
        pass

    def __init__(self, options: Options | None = None, runtime: RuntimeContext | None = None):
        self.options = options or self.Options()
        self.runtime = runtime or _test_runtime()

    @classmethod
    def make(cls, **options):
        return cls(options=cls.Options(**options))


class HashEmbedder(_Fake):
    """Deterministic unit vectors from sha256 of the text. No semantics beyond
    'identical text -> identical vector', which is all kernel tests need."""

    META = _meta("hash-embedder", ComponentKind.EMBEDDER)
    dims = 8

    def __init__(self, options=None, runtime=None):
        super().__init__(options, runtime)

    def embed(self, texts: list[str]) -> list[Vector]:
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode()).digest()
            raw = [b / 255.0 - 0.5 for b in h[: self.dims]]
            norm = math.sqrt(sum(x * x for x in raw)) or 1.0
            out.append([x / norm for x in raw])
        return out


def _matches(chunk: Chunk, filters: Filters | None) -> bool:
    if filters is None:
        return True
    values = {"id": chunk.id, "doc_id": chunk.doc_id, "position": chunk.position,
              "page": chunk.page, **chunk.metadata}
    for k, v in filters.equals.items():
        if values.get(k) != v:
            return False
    for k, allowed in filters.any_of.items():
        if values.get(k) not in allowed:
            return False
    for k, (lo, hi) in filters.ranges.items():
        val = values.get(k)
        if not isinstance(val, (int, float)) or not (lo <= val <= hi):
            return False
    return True


class FakeStore(_Fake):
    """Dict-backed store: term-frequency keyword search + cosine dense search."""

    META = _meta("fake-store", ComponentKind.STORE)
    capabilities = StoreCapabilities(native_bm25=True, supports_filters=True,
                                     supports_multivector=True)

    def __init__(self, options=None, runtime=None):
        super().__init__(options, runtime)
        self._rows: dict[str, EmbeddedChunk] = {}
        self._spec: IndexSpec | None = None

    def ensure_schema(self, spec: IndexSpec) -> None:
        self._spec = spec

    def upsert(self, chunks: list[EmbeddedChunk]) -> None:
        if self._spec is None:
            raise MadoshoError("ensure_schema() must run before upsert()")
        for ec in chunks:
            self._rows[ec.chunk.id] = ec

    def delete(self, doc_ids: list[str]) -> None:
        self._rows = {k: v for k, v in self._rows.items() if v.chunk.doc_id not in doc_ids}

    def keyword_search(self, query: str, k: int, filters: Filters | None = None) -> list[Hit]:
        terms = query.lower().split()
        scored = []
        for ec in self._rows.values():
            if not _matches(ec.chunk, filters):
                continue
            # scores over embed_text (incl. context prefix); rerankers score body text only — deliberate
            words = ec.chunk.embed_text.lower().split()
            score = float(sum(words.count(t) for t in terms))
            if score > 0:
                scored.append(Hit(chunk_id=ec.chunk.id, score=score,
                                  source_index="bm25", chunk=ec.chunk))
        scored.sort(key=lambda h: (-h.score, h.chunk_id))
        return scored[:k]

    def semantic_search(self, vector: Vector, k: int, filters: Filters | None = None) -> list[Hit]:
        scored = []
        for ec in self._rows.values():
            if not _matches(ec.chunk, filters):
                continue
            dense = ec.vectors["dense"]
            cos = sum(a * b for a, b in zip(vector, dense))
            scored.append(Hit(chunk_id=ec.chunk.id, score=cos,
                              source_index="dense", chunk=ec.chunk))
        scored.sort(key=lambda h: (-h.score, h.chunk_id))
        return scored[:k]

    def read(self, chunk_ids: list[str], window: int = 0) -> list[Chunk]:
        out: dict[str, Chunk] = {}
        for cid in chunk_ids:
            ec = self._rows.get(cid)
            if ec is None:
                continue
            lo, hi = ec.chunk.position - window, ec.chunk.position + window
            for other in self._rows.values():
                c = other.chunk
                if c.doc_id == ec.chunk.doc_id and lo <= c.position <= hi:
                    out[c.id] = c
        return sorted(out.values(), key=lambda c: (c.doc_id, c.position))

    def multivector_search(self, name: str, vectors: list[Vector], k: int,
                           filters: Filters | None = None) -> list[Hit]:
        # Brute-force MaxSim: per query vector, the best dot product over the
        # chunk's token vectors; sum over query vectors.
        if not vectors:
            return []
        scored = []
        for ec in self._rows.values():
            if not _matches(ec.chunk, filters):
                continue
            doc_vecs = ec.multivectors.get(name)
            if not doc_vecs:
                continue
            score = sum(max(sum(a * b for a, b in zip(q, d)) for d in doc_vecs)
                        for q in vectors)
            scored.append(Hit(chunk_id=ec.chunk.id, score=score,
                              source_index=name, chunk=ec.chunk))
        scored.sort(key=lambda h: (-h.score, h.chunk_id))
        return scored[:k]


class FakeParser(_Fake):
    """Parses .txt files into one TEXT block per paragraph."""

    META = _meta("fake-parser", ComponentKind.PARSER)

    def supports(self, file: SourceFile) -> bool:
        return file.path.endswith(".txt")

    def parse(self, file: SourceFile) -> Document:
        text = Path(file.path).read_text()
        prov = Provenance(source=file.path, page=1)
        blocks = [Block(kind=BlockKind.TEXT, content=p.strip(), provenance=prov)
                  for p in text.split("\n\n") if p.strip()]
        return Document(doc_id=hashlib.sha256(file.path.encode()).hexdigest()[:16],
                        source=file, blocks=blocks)


class FakeChunker(_Fake):
    """One chunk per block; heading blocks become the context prefix."""

    META = _meta("fake-chunker", ComponentKind.CHUNKER)

    def chunk(self, doc: Document) -> list[Chunk]:
        chunks, prefix = [], ""
        for i, block in enumerate(doc.blocks):
            if block.kind == BlockKind.HEADING:
                prefix = block.content
                continue
            chunks.append(Chunk(id=f"{doc.doc_id}-{i}", doc_id=doc.doc_id,
                                text=block.content, context_prefix=prefix,
                                position=len(chunks), page=block.provenance.page,
                                metadata={"source": doc.source.path}))
        return chunks


class FakeReranker(_Fake):
    """Scores by token overlap with the query. Deterministic."""

    META = _meta("fake-reranker", ComponentKind.RERANKER)

    def rerank(self, query: str, hits: list[Hit], top_k: int) -> list[Hit]:
        terms = set(query.lower().split())
        # scores chunk.text (body only), not embed_text — rerankers judge content, not headings
        rescored = [h.model_copy(update={
            "score": float(len(terms & set(h.chunk.text.lower().split()))),
            "source_index": "rerank"}) for h in hits]
        rescored.sort(key=lambda h: (-h.score, h.chunk_id))
        return rescored[:top_k]
