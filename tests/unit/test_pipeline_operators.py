from madosho.core.types import Chunk, Hit, QueryContext
from madosho.operators.chunk_read import ChunkRead
from madosho.operators.fuse import Fuse
from madosho.operators.rerank import Rerank

from .test_fakes import seeded_store
from .test_search_operators import deps


def hit(cid, score, idx="bm25", doc="d", pos=0, text=None):
    return Hit(chunk_id=cid, score=score, source_index=idx,
               chunk=Chunk(id=cid, doc_id=doc, text=text or f"text {cid}", position=pos))


def test_rrf_rewards_presence_in_both_pools():
    ctx = QueryContext(query="q")
    ctx.pools = [
        [hit("a", 10.0), hit("b", 5.0)],          # bm25: a then b
        [hit("c", 0.9, "dense"), hit("a", 0.8, "dense")],  # dense: c then a
    ]
    store, emb = seeded_store()
    ctx = Fuse.make(method="rrf").run(ctx, deps(store, emb))
    assert ctx.hits[0].chunk_id == "a"            # in both pools -> wins
    assert {h.chunk_id for h in ctx.hits} == {"a", "b", "c"}
    assert all(h.source_index == "rrf" for h in ctx.hits)


def test_rerank_delegates_to_named_reranker():
    ctx = QueryContext(query="alpha beta")
    ctx.hits = [hit("1", 0.1, text="gamma"), hit("2", 0.2, text="alpha beta")]
    store, emb = seeded_store()
    ctx = Rerank.make(model="anything", top_k=1).run(ctx, deps(store, emb))
    assert [h.chunk_id for h in ctx.hits] == ["2"]


def test_chunk_read_expands_hits_with_window():
    store, emb = seeded_store()
    ctx = QueryContext(query="q")
    ctx.hits = [store.keyword_search("termination", k=1)[0]]   # a1
    ctx = ChunkRead.make(window=1).run(ctx, deps(store, emb))
    assert "thirty days" in ctx.hits[0].chunk.text             # a2 merged in


def test_params_schema_auto_binds_to_subclass_options():
    from pydantic import BaseModel

    from madosho.operators._base import OperatorBase

    class Forgetful(OperatorBase):
        name = "forgetful"

        class Options(BaseModel):
            knob: int = 1
        # note: no `params_schema = Options` re-point

    assert Forgetful.params_schema is Forgetful.Options
