import pytest

pytest.importorskip("sentence_transformers")
pytestmark = pytest.mark.slow

from madosho.core.types import Chunk, Hit
from madosho.testing.contracts import EmbedderContractTests, RerankerContractTests
from madosho.adapters.st_models.embedder import MiniLmEmbedder, StEmbedder
from madosho.adapters.st_models.reranker import StCrossEncoderReranker


class TestGraniteEmbedderContract(EmbedderContractTests):
    @pytest.fixture(scope="class")
    def embedder(self):
        return StEmbedder.make()


class TestMiniLmEmbedderContract(EmbedderContractTests):
    @pytest.fixture(scope="class")
    def embedder(self):
        return MiniLmEmbedder.make()


def test_minilm_dims_are_384():
    # 384-dim (vs granite's 768) is what makes the two pipelines' indexes
    # genuinely different shapes and exercises the heterogeneous-embedder path
    assert MiniLmEmbedder.make().dims == 384


def test_embedder_semantic_sanity():
    emb = StEmbedder.make()
    q, pos, neg = emb.embed([
        "what does the termination clause say",
        "the termination clause requires ninety days notice",
        "bananas are rich in potassium",
    ])
    cos = lambda a, b: sum(x * y for x, y in zip(a, b))
    assert cos(q, pos) > cos(q, neg)


class TestGraniteRerankerContract(RerankerContractTests):
    @pytest.fixture(scope="class")
    def reranker(self):
        return StCrossEncoderReranker.make()


def test_reranker_top_k_and_scores():
    rr = StCrossEncoderReranker.make()
    chunks = [
        Chunk(id="1", doc_id="d", text="the termination clause requires ninety days notice"),
        Chunk(id="2", doc_id="d", text="our cafeteria serves lunch at noon"),
    ]
    hits = [Hit(chunk_id=c.id, score=0.0, source_index="bm25", chunk=c) for c in chunks]
    out = rr.rerank("termination clause notice period", hits, top_k=1)
    assert out[0].chunk_id == "1" and out[0].source_index == "rerank"


def test_embed_empty_list_returns_empty():
    assert StEmbedder.make().embed([]) == []


def test_batch_size_must_be_positive():
    with pytest.raises(Exception):
        StEmbedder.make(batch_size=0)
