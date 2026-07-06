import pytest

pytest.importorskip("qdrant_client")

from madosho.adapters.qdrant.store import QdrantStore
from madosho.core.errors import MadoshoError
from madosho.core.types import Chunk, EmbeddedChunk, Filters, IndexSpec


def make_store(**overrides):
    options = {"location": ":memory:", "collection": "chunks"} | overrides
    return QdrantStore.make(**options)


SPEC = IndexSpec(indexes=["bm25", "dense"], vectors={"dense": 8},
                 multivectors={"late": 4})


def test_needs_collection_or_runtime():
    with pytest.raises(MadoshoError, match="collection"):
        QdrantStore.make(location=":memory:")


def test_rejects_multiple_connection_modes():
    with pytest.raises(MadoshoError, match="at most one"):
        QdrantStore.make(location=":memory:", url="http://localhost:6333",
                         collection="chunks")


def test_native_exposes_qdrant_client():
    store = make_store()
    assert store.native is not None  # raw QdrantClient (escape hatch, kernel spec §5.2.2)


def test_ensure_schema_is_idempotent():
    store = make_store()
    store.ensure_schema(SPEC)
    store.ensure_schema(SPEC)   # must not raise "already exists"


def test_ensure_schema_validates_dims_of_existing_collection():
    store = make_store()
    store.ensure_schema(SPEC)
    bad = IndexSpec(indexes=["bm25", "dense"], vectors={"dense": 16},
                    multivectors={"late": 4})
    with pytest.raises(MadoshoError, match="dense.*16.*8"):
        store.ensure_schema(bad)


def test_ensure_schema_rejects_missing_named_vector():
    store = make_store()
    store.ensure_schema(IndexSpec(indexes=["dense"], vectors={"dense": 8}))
    with pytest.raises(MadoshoError, match="late"):
        store.ensure_schema(SPEC)   # existing collection has no 'late'


def test_vector_dims_reports_collection_dims():
    store = make_store()
    store.ensure_schema(SPEC)
    assert store.vector_dims() == {"dense": 8, "late": 4}


def test_ensure_schema_rejects_unnamed_vector_collection():
    from qdrant_client import models

    store = make_store()
    store.native.create_collection(
        "chunks", vectors_config=models.VectorParams(
            size=8, distance=models.Distance.COSINE))
    with pytest.raises(MadoshoError, match="unnamed vector layout"):
        store.ensure_schema(SPEC)


def test_ensure_schema_rejects_existing_collection_without_sparse_index():
    store = make_store()
    store.ensure_schema(IndexSpec(indexes=["dense"], vectors={"dense": 8},
                                  multivectors={"late": 4}))
    with pytest.raises(MadoshoError, match="bm25"):
        store.ensure_schema(SPEC)


from madosho.testing.contracts import MultiVectorStoreContractTests, StoreContractTests


class TestQdrantStoreContract(StoreContractTests):
    @pytest.fixture
    def store(self):
        return make_store()


def _seeded():
    store = make_store()
    store.ensure_schema(IndexSpec(indexes=["bm25", "dense"], vectors={"dense": 4}))
    store.upsert([EmbeddedChunk(
        chunk=Chunk(id="a1", doc_id="doc-a", text="the termination clause",
                    metadata={"source": "a.txt", "lang": "en"}),
        vectors={"dense": [1.0, 0.0, 0.0, 0.0]})])
    return store


def test_empty_any_of_matches_nothing():
    assert _seeded().keyword_search(
        "termination", k=5, filters=Filters(any_of={"doc_id": []})) == []


def test_hostile_filter_key_is_rejected():
    with pytest.raises(MadoshoError, match="unknown filter column"):
        _seeded().keyword_search(
            "termination", k=5,
            filters=Filters(equals={"doc_id = 'x' OR 1=1 --": "y"}))


def test_metadata_roundtrip_preserves_all_keys():
    # unlike the LanceDB store (README known limitation), payloads are schemaless
    chunk = _seeded().read(["a1"])[0]
    assert chunk.metadata == {"source": "a.txt", "lang": "en"}


def test_upsert_missing_declared_vector_raises():
    store = make_store()
    store.ensure_schema(IndexSpec(indexes=["dense"], vectors={"dense": 4}))
    with pytest.raises(MadoshoError, match="missing.*dense"):
        store.upsert([EmbeddedChunk(chunk=Chunk(id="x", doc_id="d", text="t"),
                                    vectors={"other": [1.0, 0.0, 0.0, 0.0]})])


def test_keyword_search_without_bm25_index_raises():
    store = make_store()
    store.ensure_schema(IndexSpec(indexes=["dense"], vectors={"dense": 4}))
    with pytest.raises(MadoshoError, match="bm25"):
        store.keyword_search("anything", k=1)


def test_search_before_ensure_schema_raises():
    store = make_store()
    with pytest.raises(MadoshoError, match="ensure_schema"):
        store.keyword_search("anything", k=1)


def test_empty_query_returns_no_hits():
    assert _seeded().keyword_search("...", k=5) == []


def test_float_equals_filter_translates_to_range():
    store = _seeded()
    hits = store.keyword_search("termination", k=5,
                                filters=Filters(equals={"position": 0.0}))
    assert [h.chunk.id for h in hits] == ["a1"]


def test_read_window_fetches_all_rows_even_with_duplicate_positions():
    store = make_store()
    store.ensure_schema(IndexSpec(indexes=["dense"], vectors={"dense": 4}))
    v = {"dense": [1.0, 0.0, 0.0, 0.0]}
    store.upsert([
        EmbeddedChunk(chunk=Chunk(id="c0", doc_id="doc-a", text="zero", position=0), vectors=v),
        EmbeddedChunk(chunk=Chunk(id="c1", doc_id="doc-a", text="one", position=1), vectors=v),
        EmbeddedChunk(chunk=Chunk(id="c1b", doc_id="doc-a", text="one-b", position=1), vectors=v),
        EmbeddedChunk(chunk=Chunk(id="c2", doc_id="doc-a", text="two", position=2), vectors=v),
    ])
    # 2*window+1 = 3 would truncate one of the four qualifying rows
    assert {c.id for c in store.read(["c1"], window=1)} == {"c0", "c1", "c1b", "c2"}


def test_read_window_zero_returns_exactly_the_anchor():
    store = make_store()
    store.ensure_schema(IndexSpec(indexes=["dense"], vectors={"dense": 4}))
    v = {"dense": [1.0, 0.0, 0.0, 0.0]}
    store.upsert([
        EmbeddedChunk(chunk=Chunk(id="d0", doc_id="doc-b", text="zero", position=0), vectors=v),
        EmbeddedChunk(chunk=Chunk(id="d1", doc_id="doc-b", text="one", position=1), vectors=v),
        EmbeddedChunk(chunk=Chunk(id="d2", doc_id="doc-b", text="two", position=2), vectors=v),
    ])
    assert [c.id for c in store.read(["d1"], window=0)] == ["d1"]


class TestQdrantStoreMultiVectorContract(MultiVectorStoreContractTests):
    @pytest.fixture
    def store(self):
        return make_store()


def test_multivector_search_unknown_name_raises():
    store = make_store()
    store.ensure_schema(SPEC)
    with pytest.raises(MadoshoError, match="nope"):
        store.multivector_search("nope", [[1.0, 0.0, 0.0, 0.0]], k=1)


def test_multivector_search_empty_query_returns_no_hits():
    store = make_store()
    store.ensure_schema(SPEC)
    assert store.multivector_search("late", [], k=5) == []


def test_registry_resolves_qdrant_store(tmp_path):
    import logging

    from madosho.core.hooks import ResolutionContext
    from madosho.core.meta import ComponentKind
    from madosho.core.protocols import RuntimeContext
    from madosho.core.registry import Registry

    runtime = RuntimeContext(corpus="reg-test", data_dir=tmp_path, cache_dir=None,
                             logger=logging.getLogger("test"))
    store = Registry().resolve(ComponentKind.STORE, "qdrant",
                               {"location": ":memory:"}, runtime,
                               ResolutionContext(corpus="reg-test", config_path="x"))
    assert isinstance(store, QdrantStore)
    assert store._collection == "madosho_reg_test"   # corpus name sanitized
