import logging

import pytest

from madosho.core.errors import CapabilityError
from madosho.core.meta import StoreCapabilities
from madosho.core.protocols import OperatorDeps, RuntimeContext
from madosho.core.types import QueryContext
from madosho.operators.keyword_search import KeywordSearch
from madosho.operators.semantic_search import SemanticSearch
from madosho.testing.fakes import FakeReranker, FakeStore, HashEmbedder

from .test_fakes import seeded_store  # reuse the seeded fixture helper


def deps(store, emb) -> OperatorDeps:
    rt = RuntimeContext(corpus="c", data_dir=None, cache_dir=None,
                        logger=logging.getLogger("madosho.test"))
    return OperatorDeps(store=store, embedder=emb,
                        reranker_for=lambda name: FakeReranker.make(), runtime=rt)


def test_keyword_search_appends_pool_and_trace():
    store, emb = seeded_store()
    op = KeywordSearch.make(k=2)
    ctx = op.run(QueryContext(query="termination clause"), deps(store, emb))
    assert len(ctx.pools) == 1 and ctx.pools[0][0].chunk_id == "a1"
    assert ctx.trace[0].operator == "keyword_search" and ctx.trace[0].added == len(ctx.pools[0])


def test_keyword_search_requires_native_bm25():
    store, emb = seeded_store()
    store.capabilities = StoreCapabilities(native_bm25=False)
    with pytest.raises(CapabilityError, match="native_bm25"):
        KeywordSearch.make(k=2).run(QueryContext(query="x"), deps(store, emb))


def test_semantic_search_uses_cached_query_vector():
    store, emb = seeded_store()
    ctx = QueryContext(query="the termination clause requires notice")
    ctx = SemanticSearch.make(k=1).run(ctx, deps(store, emb))
    assert ctx.pools[0][0].chunk_id == "a1"
    assert ctx._query_vector is not None  # cached for any later operator


def test_two_searches_make_two_pools():
    store, emb = seeded_store()
    d = deps(store, emb)
    ctx = QueryContext(query="termination clause")
    ctx = KeywordSearch.make(k=2).run(ctx, d)
    ctx = SemanticSearch.make(k=2).run(ctx, d)
    assert len(ctx.pools) == 2
