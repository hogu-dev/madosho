# tests/unit/test_kb_index.py
"""Page-level KB semantic index (kb_index) with injected fakes - no qdrant,
no sentence-transformers."""
import math

from madosho_server import kb_index
from madosho.core.types import Hit


class FakeEmbedder:
    """Deterministic bag-of-words embedder over a fixed vocab, so cosine
    ranking is meaningful without a real model."""
    VOCAB = ["flight", "control", "engine", "saturn", "rocket", "digital"]

    def __init__(self):
        self.dims = len(self.VOCAB)
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        out = []
        for t in texts:
            low = (t or "").lower()
            v = [float(low.count(w)) for w in self.VOCAB]
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


class FakeStore:
    """In-memory stand-in for QdrantStore: keeps one point per doc_id and
    ranks by cosine on semantic_search."""
    def __init__(self):
        self.schema = None
        self.points = {}   # doc_id -> (chunk, vector)

    def ensure_schema(self, spec):
        self.schema = spec

    def upsert(self, embedded):
        for ec in embedded:
            self.points[ec.chunk.doc_id] = (ec.chunk, ec.vectors["dense"])

    def delete(self, doc_ids):
        for d in doc_ids:
            self.points.pop(d, None)

    def semantic_search(self, vector, k, filters=None):
        def cos(a, b):
            return sum(x * y for x, y in zip(a, b))
        ranked = sorted(self.points.values(), key=lambda cv: cos(vector, cv[1]), reverse=True)
        return [Hit(chunk_id=c.id, score=cos(vector, v), source_index="dense", chunk=c)
                for c, v in ranked[:k]]


def _page(slug, title, description="", body="", type="concept"):
    return {"slug": slug, "title": title, "description": description, "body": body, "type": type}


def test_kb_collection_name():
    assert kb_index.kb_collection(7) == "madosho_kb_7"


def test_page_embed_text_joins_title_desc_body_and_drops_blanks():
    txt = kb_index.page_embed_text(_page("s", "Title", description="", body="Body here"))
    assert txt == "Title\n\nBody here"


def test_index_page_embeds_and_upserts_one_point_per_slug():
    store, emb = FakeStore(), FakeEmbedder()
    kb_index.index_page(store, emb, 5, _page("afti", "AFTI flight control", body="digital flight control"))
    assert store.schema.vectors == {"dense": emb.dims}
    assert set(store.points) == {"afti"}
    chunk, _ = store.points["afti"]
    assert chunk.metadata["kb_id"] == "5" and chunk.metadata["title"] == "AFTI flight control"


def test_index_page_is_idempotent_overwrite_on_edit():
    store, emb = FakeStore(), FakeEmbedder()
    kb_index.index_page(store, emb, 5, _page("afti", "old", body="engine"))
    kb_index.index_page(store, emb, 5, _page("afti", "new title", body="rocket"))
    assert len(store.points) == 1
    assert store.points["afti"][0].metadata["title"] == "new title"


def test_remove_page_drops_the_vector():
    store, emb = FakeStore(), FakeEmbedder()
    kb_index.index_page(store, emb, 5, _page("afti", "AFTI", body="flight"))
    kb_index.remove_page(store, "afti")
    assert store.points == {}


def test_reindex_batches_all_pages_and_returns_count():
    store, emb = FakeStore(), FakeEmbedder()
    pages = [_page("a", "Saturn V", body="saturn rocket engine"),
             _page("b", "AFTI", body="digital flight control")]
    n = kb_index.reindex(store, emb, 5, pages)
    assert n == 2 and set(store.points) == {"a", "b"}
    # one batched embed call for both page texts
    assert len(emb.calls[-1]) == 2


def test_reindex_empty_is_a_noop_count_zero():
    store, emb = FakeStore(), FakeEmbedder()
    assert kb_index.reindex(store, emb, 5, []) == 0
    assert store.points == {}


def test_search_ranks_pages_by_semantic_similarity():
    store, emb = FakeStore(), FakeEmbedder()
    kb_index.reindex(store, emb, 5, [
        _page("saturn", "Saturn V", body="saturn rocket engine"),
        _page("afti", "AFTI", body="digital flight control")])
    hits = kb_index.search(store, emb, "flight control", k=2)
    assert [h.chunk_id for h in hits][0] == "afti"   # closest to the query
    assert all(isinstance(h, Hit) for h in hits)


# -- fusion (lexical + semantic) --------------------------------------------

def _hit(slug, score, title="", description="", type="concept"):
    from madosho.core.types import Chunk
    ch = Chunk(id=slug, doc_id=slug, text="",
               metadata={"slug": slug, "type": type, "title": title, "description": description})
    return Hit(chunk_id=slug, score=score, source_index="dense", chunk=ch)


def test_rrf_fuse_ranks_shared_slugs_higher():
    fused = kb_index.rrf_fuse([["a", "b", "c"], ["b", "a", "d"]])
    # b and a appear in both; b is rank0+rank1, a is rank1+rank0 -> tie, both above c/d
    assert set(fused[:2]) == {"a", "b"}
    assert set(fused) == {"a", "b", "c", "d"}


def test_fuse_unions_lexical_and_semantic_and_returns_full_summaries():
    lexical = [{"slug": "afti", "type": "concept", "title": "AFTI", "description": "d"}]
    semantic = [_hit("saturn", 0.9, title="Saturn V", description="rocket"),
                _hit("afti", 0.5, title="AFTI", description="d")]
    out = kb_index.fuse(lexical, semantic, limit=10)
    slugs = [p["slug"] for p in out]
    assert set(slugs) == {"afti", "saturn"}            # semantic-only 'saturn' included
    saturn = next(p for p in out if p["slug"] == "saturn")
    assert saturn["title"] == "Saturn V"               # summary from hit metadata


def test_fuse_lexical_only_when_no_semantic():
    lexical = [{"slug": "afti", "type": "concept", "title": "AFTI", "description": "d"}]
    out = kb_index.fuse(lexical, [], limit=10)
    assert [p["slug"] for p in out] == ["afti"]


def test_fuse_respects_limit():
    lexical = [{"slug": f"p{i}", "type": "concept", "title": "", "description": ""} for i in range(5)]
    out = kb_index.fuse(lexical, [], limit=2)
    assert len(out) == 2
