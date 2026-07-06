import pytest

pytest.importorskip("lancedb")

from madosho.adapters.lancedb.store import LanceDBStore
from madosho.testing.contracts import StoreContractTests


class TestLanceDBStoreContract(StoreContractTests):
    @pytest.fixture
    def store(self, tmp_path):
        return LanceDBStore.make(uri=str(tmp_path / "lancedb"))


def _seeded(tmp_path):
    from madosho.core.types import Chunk, EmbeddedChunk, IndexSpec

    store = LanceDBStore.make(uri=str(tmp_path / "lancedb"))
    store.ensure_schema(IndexSpec(indexes=["bm25", "dense"], vectors={"dense": 4}))
    store.upsert([EmbeddedChunk(chunk=Chunk(id="a1", doc_id="doc-a", text="the termination clause"),
                                vectors={"dense": [1.0, 0.0, 0.0, 0.0]})])
    return store


def test_native_exposes_lancedb_connection(tmp_path):
    store = LanceDBStore.make(uri=str(tmp_path / "lancedb"))
    assert store.native is not None  # raw lancedb connection (escape hatch, spec §5.2.2)


def test_reopen_existing_store_preserves_rows(tmp_path):
    from madosho.core.types import Chunk, EmbeddedChunk, IndexSpec

    uri = str(tmp_path / "lancedb")
    spec = IndexSpec(indexes=["bm25", "dense"], vectors={"dense": 4})
    first = LanceDBStore.make(uri=uri)
    first.ensure_schema(spec)
    first.upsert([EmbeddedChunk(chunk=Chunk(id="x1", doc_id="d", text="persisted row"),
                                vectors={"dense": [1.0, 0.0, 0.0, 0.0]})])
    second = LanceDBStore.make(uri=uri)
    second.ensure_schema(spec)   # must not raise "already exists"
    assert [h.chunk.id for h in second.keyword_search("persisted", k=5)] == ["x1"]


def test_empty_any_of_matches_nothing(tmp_path):
    from madosho.core.types import Filters
    store = _seeded(tmp_path)
    assert store.keyword_search("termination", k=5,
                                filters=Filters(any_of={"doc_id": []})) == []


def test_hostile_filter_key_is_rejected(tmp_path):
    from madosho.core.errors import MadoshoError
    from madosho.core.types import Filters
    store = _seeded(tmp_path)
    with pytest.raises(MadoshoError, match="unknown filter column"):
        store.keyword_search("termination", k=5,
                             filters=Filters(equals={"doc_id = 'x' OR 1=1 --": "y"}))
