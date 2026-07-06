"""Run against a real Qdrant server: the same
contract batteries as local mode, server-only behaviors (reopen from a second
client), and the quickstart config path end-to-end. The image is pinned to the
installed qdrant-client's series (testcontainers' default lags too far behind);
deployment-grade version pinning belongs to the docker-compose setup."""
import textwrap
import uuid

import pytest

pytest.importorskip("qdrant_client")
pytest.importorskip("testcontainers.qdrant")

from madosho.adapters.qdrant.store import QdrantStore
from madosho.core.types import Chunk, EmbeddedChunk, IndexSpec
from madosho.testing.contracts import MultiVectorStoreContractTests, StoreContractTests

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def qdrant_url():
    from testcontainers.qdrant import QdrantContainer
    import importlib.metadata

    # Derive the server image from the installed client version (Qdrant publishes
    # matching vX.Y.Z server tags). This ensures client and server can't silently
    # drift apart — unlike testcontainers' unpinned default (v1.13.5), which is
    # incompatible with qdrant-client>=1.18.
    client_version = importlib.metadata.version("qdrant-client")
    qc = QdrantContainer(image=f"qdrant/qdrant:v{client_version}")
    # Set STORAGE_PATH to /tmp so RocksDB avoids overlay2 file-locking issues
    # that cause "Unable to persist options" errors in Docker-on-overlayfs.
    qc.with_env("QDRANT__STORAGE__STORAGE_PATH", "/tmp/qdrant-storage")
    with qc:
        yield f"http://{qc.get_container_host_ip()}:{qc.get_exposed_port(6333)}"


@pytest.fixture
def server_store(qdrant_url):
    # unique collection per test = the fresh, empty store the batteries require
    return QdrantStore.make(url=qdrant_url, collection=f"contract_{uuid.uuid4().hex}")


class TestQdrantServerStoreContract(StoreContractTests):
    @pytest.fixture
    def store(self, server_store):
        return server_store


class TestQdrantServerMultiVectorContract(MultiVectorStoreContractTests):
    @pytest.fixture
    def store(self, server_store):
        return server_store


def test_second_client_sees_first_clients_rows(qdrant_url):
    name = f"reopen_{uuid.uuid4().hex}"
    spec = IndexSpec(indexes=["bm25", "dense"], vectors={"dense": 4})
    first = QdrantStore.make(url=qdrant_url, collection=name)
    first.ensure_schema(spec)
    first.upsert([EmbeddedChunk(chunk=Chunk(id="x1", doc_id="d", text="persisted row"),
                                vectors={"dense": [1.0, 0.0, 0.0, 0.0]})])
    second = QdrantStore.make(url=qdrant_url, collection=name)
    second.ensure_schema(spec)   # must not raise; dims validated against live collection
    assert [h.chunk.id for h in second.keyword_search("persisted", k=5)] == ["x1"]


def test_quickstart_config_runs_against_container(qdrant_url, tmp_path):
    """The README quickstart shape (madosho.yaml -> open -> ingest -> query) with
    store: qdrant. Fakes + hash embedder keep it model-free; the store is real."""
    import madosho

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "contract.txt").write_text(
        "Service Agreement\n\nThe termination clause requires ninety days "
        "written notice before the agreement may be ended.")
    (docs / "invoice.txt").write_text(
        "Billing\n\nInvoices are payable within thirty days of receipt.")
    (tmp_path / "madosho.yaml").write_text(textwrap.dedent(f"""\
        corpus: quickstart
        source: ./docs
        ingest:
          parser: fake-parser
          chunker: fake-chunker
          embedder: hash-embedder
          store:
            qdrant:
              url: {qdrant_url}
          indexes: [bm25, dense]
        query:
          - keyword_search: {{k: 10}}
          - semantic_search: {{k: 10}}
          - fuse: {{method: rrf}}
        """))
    corpus = madosho.open(tmp_path / "madosho.yaml")
    report = corpus.ingest()
    assert report.processed == 2 and report.failed == 0
    hits = corpus.query("What does the termination clause require?")
    assert hits and any("termination" in h.text for h in hits)
    # ingest is idempotent against the server store too
    assert corpus.ingest().skipped == 2
