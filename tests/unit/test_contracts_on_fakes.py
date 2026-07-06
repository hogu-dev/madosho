import pytest

from madosho.testing.contracts import (
    ChunkerContractTests, EmbedderContractTests, MultiVectorStoreContractTests,
    ParserContractTests, RerankerContractTests, StoreContractTests,
)
from madosho.testing.fakes import (
    FakeChunker, FakeParser, FakeReranker, FakeStore, HashEmbedder,
)


class TestFakeStoreContract(StoreContractTests):
    @pytest.fixture
    def store(self):
        return FakeStore.make()


class TestHashEmbedderContract(EmbedderContractTests):
    @pytest.fixture
    def embedder(self):
        return HashEmbedder.make()


class TestFakeParserContract(ParserContractTests):
    @pytest.fixture
    def parser(self):
        return FakeParser.make()

    @pytest.fixture
    def sample_file(self, tmp_path):
        p = tmp_path / "sample.txt"
        p.write_text("Alpha paragraph.\n\nBeta paragraph.")
        return p


class TestFakeChunkerContract(ChunkerContractTests):
    @pytest.fixture
    def chunker(self):
        return FakeChunker.make()


class TestFakeRerankerContract(RerankerContractTests):
    @pytest.fixture
    def reranker(self):
        return FakeReranker.make()


class TestFakeStoreMultiVectorContract(MultiVectorStoreContractTests):
    @pytest.fixture
    def store(self):
        return FakeStore.make()
