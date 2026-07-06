from madosho.core.types import (
    Block, BlockKind, Chunk, Document, EmbeddedChunk, Filters, Hit,
    IndexSpec, Provenance, SourceFile,
)
from madosho.testing.fakes import (
    FakeChunker, FakeParser, FakeReranker, FakeStore, HashEmbedder,
)


def embedded(id, doc_id, text, emb, position=0):
    c = Chunk(id=id, doc_id=doc_id, text=text, position=position)
    return EmbeddedChunk(chunk=c, vectors={"dense": emb.embed([c.embed_text])[0]})


def seeded_store():
    emb = HashEmbedder()
    store = FakeStore.make()
    store.ensure_schema(IndexSpec(vectors={"dense": emb.dims}))
    store.upsert([
        embedded("a1", "doc-a", "the termination clause requires notice", emb, 0),
        embedded("a2", "doc-a", "payment is due in thirty days", emb, 1),
        embedded("b1", "doc-b", "the parties agree to arbitration", emb, 0),
    ])
    return store, emb


def test_hash_embedder_deterministic_unit_vectors():
    emb = HashEmbedder()
    v1, v2 = emb.embed(["hello", "hello"])
    assert v1 == v2 and len(v1) == emb.dims
    assert abs(sum(x * x for x in v1) - 1.0) < 1e-6


def test_keyword_search_ranks_term_overlap():
    store, _ = seeded_store()
    hits = store.keyword_search("termination clause", k=2)
    assert hits[0].chunk_id == "a1" and hits[0].source_index == "bm25"


def test_semantic_search_finds_identical_text():
    store, emb = seeded_store()
    vec = emb.embed(["the termination clause requires notice"])[0]
    hits = store.semantic_search(vec, k=1)
    assert hits[0].chunk_id == "a1" and hits[0].source_index == "dense"


def test_delete_removes_whole_doc():
    store, _ = seeded_store()
    store.delete(["doc-a"])
    assert store.keyword_search("termination", k=5) == []


def test_read_with_window_pulls_neighbors():
    store, _ = seeded_store()
    chunks = store.read(["a1"], window=1)
    assert [c.id for c in chunks] == ["a1", "a2"]


def test_filters_equals_applied():
    store, _ = seeded_store()
    hits = store.keyword_search("the", k=5, filters=Filters(equals={"doc_id": "doc-b"}))
    assert {h.chunk.doc_id for h in hits} == {"doc-b"}


def test_fake_parser_and_chunker_roundtrip(tmp_path):
    p = tmp_path / "note.txt"
    p.write_text("First paragraph.\n\nSecond paragraph.")
    sf = SourceFile(path=str(p), mimetype="text/plain", content_hash="h")
    parser, chunker = FakeParser.make(), FakeChunker.make()
    assert parser.supports(sf)
    doc = parser.parse(sf)
    chunks = chunker.chunk(doc)
    assert len(chunks) == 2 and chunks[0].doc_id == doc.doc_id
    assert chunks[0].metadata["source"] == str(p)


def test_range_filter_on_string_metadata_is_a_non_match():
    store, _ = seeded_store()
    hits = store.keyword_search("the", k=5, filters=Filters(ranges={"doc_id": (0, 10)}))
    assert hits == []


def test_fake_reranker_orders_by_token_overlap():
    c1 = Chunk(id="1", doc_id="d", text="alpha beta gamma")
    c2 = Chunk(id="2", doc_id="d", text="alpha beta")
    hits = [Hit(chunk_id=c.id, score=0.0, source_index="bm25", chunk=c) for c in (c1, c2)]
    out = FakeReranker.make().rerank("alpha beta gamma", hits, top_k=1)
    assert len(out) == 1 and out[0].chunk_id == "1"


def test_fake_store_multivector_maxsim_ranks_token_match_first():
    from madosho.core.protocols import MultiVectorSearch
    from madosho.core.types import Chunk, EmbeddedChunk, IndexSpec
    from madosho.testing.fakes import FakeStore

    store = FakeStore.make()
    assert store.capabilities.supports_multivector
    store.ensure_schema(IndexSpec(indexes=["dense"], vectors={"dense": 2},
                                  multivectors={"late": 2}))
    store.upsert([
        EmbeddedChunk(chunk=Chunk(id="m1", doc_id="d", text="hit"),
                      vectors={"dense": [1.0, 0.0]},
                      multivectors={"late": [[1.0, 0.0], [0.0, 1.0]]}),
        EmbeddedChunk(chunk=Chunk(id="m2", doc_id="d", text="miss"),
                      vectors={"dense": [0.0, 1.0]},
                      multivectors={"late": [[-1.0, 0.0]]}),
    ])
    mv = store.extension(MultiVectorSearch)
    assert mv is not None
    hits = mv.multivector_search("late", [[1.0, 0.0]], k=2)
    # MaxSim: m1 scores max(1.0, 0.0)=1.0; m2 scores -1.0
    assert [h.chunk_id for h in hits] == ["m1", "m2"]
    assert hits[0].source_index == "late"


def test_fake_store_multivector_search_respects_filters():
    from madosho.core.protocols import MultiVectorSearch
    from madosho.core.types import Chunk, EmbeddedChunk, Filters, IndexSpec
    from madosho.testing.fakes import FakeStore

    store = FakeStore.make()
    store.ensure_schema(IndexSpec(indexes=["dense"], vectors={"dense": 2},
                                  multivectors={"late": 2}))
    store.upsert([
        EmbeddedChunk(chunk=Chunk(id="m1", doc_id="doc-a", text="a"),
                      vectors={"dense": [1.0, 0.0]},
                      multivectors={"late": [[1.0, 0.0]]}),
        EmbeddedChunk(chunk=Chunk(id="m2", doc_id="doc-b", text="b"),
                      vectors={"dense": [1.0, 0.0]},
                      multivectors={"late": [[1.0, 0.0]]}),
    ])
    hits = store.extension(MultiVectorSearch).multivector_search(
        "late", [[1.0, 0.0]], k=10, filters=Filters(equals={"doc_id": "doc-b"}))
    assert [h.chunk_id for h in hits] == ["m2"]


def test_fake_store_multivector_search_empty_query_returns_no_hits():
    from madosho.core.protocols import MultiVectorSearch
    from madosho.core.types import Chunk, EmbeddedChunk, IndexSpec
    from madosho.testing.fakes import FakeStore

    store = FakeStore.make()
    store.ensure_schema(IndexSpec(indexes=["dense"], vectors={"dense": 2},
                                  multivectors={"late": 2}))
    store.upsert([EmbeddedChunk(chunk=Chunk(id="m1", doc_id="d", text="t"),
                                vectors={"dense": [1.0, 0.0]},
                                multivectors={"late": [[1.0, 0.0]]})])
    assert store.extension(MultiVectorSearch).multivector_search("late", [], k=5) == []
