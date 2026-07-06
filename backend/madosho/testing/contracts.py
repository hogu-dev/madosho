"""Importable contract batteries. Any adapter — first- or third-party — subclasses
one of these and provides the fixtures; pytest collects the inherited tests.
This is the plugin promise made testable (spec §11.1)."""
from __future__ import annotations

import hashlib

import pytest

from madosho.core.types import (
    Block, BlockKind, Chunk, Document, EmbeddedChunk, Hit, IndexSpec,
    Provenance, SourceFile,
)


def _chunk(id: str, doc_id: str, text: str, position: int = 0) -> Chunk:
    return Chunk(id=id, doc_id=doc_id, text=text, position=position,
                 metadata={"source": f"{doc_id}.txt"})


def _embed_for(store_dims: int, text: str) -> list[float]:
    h = hashlib.sha256(text.encode()).digest()
    raw = [b / 255.0 - 0.5 for b in h[:store_dims]]
    norm = sum(x * x for x in raw) ** 0.5 or 1.0
    return [x / norm for x in raw]


DIMS = 8


class StoreContractTests:
    """Subclass and provide a `store` fixture returning a fresh, empty Store."""

    @pytest.fixture
    def seeded(self, store):
        store.ensure_schema(IndexSpec(indexes=["bm25", "dense"], vectors={"dense": DIMS}))
        rows = [
            _chunk("a1", "doc-a", "the termination clause requires notice", 0),
            _chunk("a2", "doc-a", "payment is due in thirty days", 1),
            _chunk("b1", "doc-b", "the parties agree to arbitration", 0),
        ]
        store.upsert([EmbeddedChunk(chunk=c, vectors={"dense": _embed_for(DIMS, c.embed_text)})
                      for c in rows])
        return store

    def test_keyword_search_returns_relevant_hit_first(self, seeded):
        hits = seeded.keyword_search("termination clause", k=3)
        assert hits and hits[0].chunk.id == "a1"
        assert all(isinstance(h, Hit) and h.chunk is not None for h in hits)

    def test_semantic_search_finds_identical_text(self, seeded):
        vec = _embed_for(DIMS, "the termination clause requires notice")
        hits = seeded.semantic_search(vec, k=1)
        assert hits[0].chunk.id == "a1"

    def test_upsert_same_id_overwrites(self, seeded):
        c = _chunk("a1", "doc-a", "replaced text entirely", 0)
        seeded.upsert([EmbeddedChunk(chunk=c, vectors={"dense": _embed_for(DIMS, c.text)})])
        assert seeded.keyword_search("termination", k=5) == [] or \
            all(h.chunk.id != "a1" for h in seeded.keyword_search("termination", k=5))
        assert seeded.keyword_search("replaced", k=1)[0].chunk.id == "a1"

    def test_delete_removes_all_chunks_of_doc(self, seeded):
        seeded.delete(["doc-a"])
        assert seeded.keyword_search("termination", k=10) == []   # doc-a content gone
        survivors = seeded.keyword_search("parties", k=10)        # doc-b unaffected
        assert survivors and all(h.chunk.doc_id == "doc-b" for h in survivors)

    def test_read_window_returns_position_neighbors(self, seeded):
        ids = [c.id for c in seeded.read(["a1"], window=1)]
        assert ids == ["a1", "a2"]

    def test_k_limits_results(self, seeded):
        # multi-term query matches both docs (OR semantics) so k can actually limit
        assert len(seeded.keyword_search("termination arbitration", k=10)) >= 2
        assert len(seeded.keyword_search("termination arbitration", k=1)) == 1

    def test_filters_equals_scopes_results(self, seeded):
        if not seeded.capabilities.supports_filters:
            pytest.skip("store does not support filters")
        from madosho.core.types import Filters
        hits = seeded.keyword_search("termination arbitration", k=10,
                                     filters=Filters(equals={"doc_id": "doc-b"}))
        assert hits and all(h.chunk.doc_id == "doc-b" for h in hits)

    def test_filters_apply_to_semantic_search(self, seeded):
        if not seeded.capabilities.supports_filters:
            pytest.skip("store does not support filters")
        from madosho.core.types import Filters
        vec = _embed_for(DIMS, "the termination clause requires notice")
        hits = seeded.semantic_search(vec, k=10,
                                      filters=Filters(equals={"doc_id": "doc-b"}))
        assert hits and all(h.chunk.doc_id == "doc-b" for h in hits)


class EmbedderContractTests:
    """Subclass and provide an `embedder` fixture."""

    def test_dims_match_output(self, embedder):
        vecs = embedder.embed(["hello", "world"])
        assert len(vecs) == 2 and all(len(v) == embedder.dims for v in vecs)

    def test_deterministic(self, embedder):
        a, b = embedder.embed(["same text"]), embedder.embed(["same text"])
        assert a == b

    def test_unit_norm(self, embedder):
        # adapters MUST L2-normalize: stores rank dense hits by plain L2/cosine on unit vectors
        v = embedder.embed(["check norm"])[0]
        assert abs(sum(x * x for x in v) - 1.0) < 1e-3


class ParserContractTests:
    """Subclass and provide `parser` + `sample_file` (a Path it supports) fixtures."""

    @pytest.fixture
    def source_file(self, sample_file):
        return SourceFile(path=str(sample_file), mimetype="application/octet-stream",
                          content_hash="test")

    def test_supports_its_sample(self, parser, source_file):
        assert parser.supports(source_file)

    def test_parse_yields_blocks_with_provenance(self, parser, source_file):
        doc = parser.parse(source_file)
        assert isinstance(doc, Document) and doc.blocks
        assert all(b.provenance.source for b in doc.blocks)
        assert doc.doc_id and doc.source.path == source_file.path


class ChunkerContractTests:
    """Subclass and provide a `chunker` fixture."""

    @pytest.fixture
    def doc(self):
        sf = SourceFile(path="d.txt", mimetype="text/plain", content_hash="x")
        prov = Provenance(source="d.txt", page=1)
        return Document(doc_id="d", source=sf, blocks=[
            Block(kind=BlockKind.HEADING, content="Title", provenance=prov),
            Block(kind=BlockKind.TEXT, content="First body paragraph.", provenance=prov),
            Block(kind=BlockKind.TEXT, content="Second body paragraph.", provenance=prov),
        ])

    def test_chunks_carry_doc_id_and_unique_ids(self, chunker, doc):
        chunks = chunker.chunk(doc)
        assert chunks and all(c.doc_id == "d" for c in chunks)
        assert len({c.id for c in chunks}) == len(chunks)

    def test_positions_are_sequential(self, chunker, doc):
        chunks = chunker.chunk(doc)
        assert [c.position for c in chunks] == list(range(len(chunks)))


class RerankerContractTests:
    """Subclass and provide a `reranker` fixture."""

    @pytest.fixture
    def hits(self):
        texts = {"h1": "completely unrelated text", "h2": "the exact answer to the query"}
        return [Hit(chunk_id=k, score=0.0, source_index="bm25",
                    chunk=Chunk(id=k, doc_id="d", text=v)) for k, v in texts.items()]

    def test_returns_at_most_top_k_subset(self, reranker, hits):
        out = reranker.rerank("the exact answer to the query", hits, top_k=1)
        assert len(out) == 1 and out[0].chunk_id in {"h1", "h2"}

    def test_relevant_hit_ranks_first(self, reranker, hits):
        out = reranker.rerank("the exact answer to the query", hits, top_k=2)
        assert out[0].chunk_id == "h2"


class MultiVectorStoreContractTests:
    """Subclass and provide a `store` fixture returning a fresh, empty Store.
    Tests skip automatically when the store lacks supports_multivector."""

    @pytest.fixture
    def seeded(self, store):
        if not store.capabilities.supports_multivector:
            pytest.skip("store does not support multivectors")
        store.ensure_schema(IndexSpec(indexes=["bm25", "dense"],
                                      vectors={"dense": DIMS},
                                      multivectors={"late": DIMS}))
        rows = [
            _chunk("a1", "doc-a", "the termination clause requires notice", 0),
            _chunk("a2", "doc-a", "payment is due in thirty days", 1),
            _chunk("b1", "doc-b", "the parties agree to arbitration", 0),
        ]
        store.upsert([EmbeddedChunk(
            chunk=c,
            vectors={"dense": _embed_for(DIMS, c.embed_text)},
            # one token vector per word: hash embeddings make identical words
            # identical vectors, so MaxSim has exact matches to find
            multivectors={"late": [_embed_for(DIMS, w) for w in c.text.split()]})
            for c in rows])
        return store

    def _mv(self, store):
        from madosho.core.protocols import MultiVectorSearch
        ext = store.extension(MultiVectorSearch)
        assert ext is not None, \
            "supports_multivector=True but extension(MultiVectorSearch) is None"
        return ext

    def test_extension_is_discoverable(self, seeded):
        self._mv(seeded)

    def test_maxsim_ranks_chunk_with_matching_tokens_first(self, seeded):
        query = [_embed_for(DIMS, "termination"), _embed_for(DIMS, "clause")]
        hits = self._mv(seeded).multivector_search("late", query, k=3)
        assert hits and hits[0].chunk.id == "a1"
        assert hits[0].source_index == "late"
        assert all(isinstance(h, Hit) and h.chunk is not None for h in hits)

    def test_k_limits_results(self, seeded):
        query = [_embed_for(DIMS, "termination")]
        assert len(self._mv(seeded).multivector_search("late", query, k=1)) == 1

    def test_filters_scope_results(self, seeded):
        if not seeded.capabilities.supports_filters:
            pytest.skip("store does not support filters")
        from madosho.core.types import Filters
        query = [_embed_for(DIMS, "termination")]
        hits = self._mv(seeded).multivector_search(
            "late", query, k=10, filters=Filters(equals={"doc_id": "doc-b"}))
        assert hits and all(h.chunk.doc_id == "doc-b" for h in hits)

    def test_delete_removes_multivector_hits(self, seeded):
        seeded.delete(["doc-a"])
        query = [_embed_for(DIMS, "termination")]
        hits = self._mv(seeded).multivector_search("late", query, k=10)
        assert hits and all(h.chunk.doc_id == "doc-b" for h in hits)
