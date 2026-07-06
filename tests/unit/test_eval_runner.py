# tests/unit/test_eval_runner.py
"""Trunk reuse. Query-side candidates reuse the baseline collection (no
indexing); chunk/embed candidates build an ephemeral collection once and reuse it.
We inject a fake opener + a fake corpus so the test counts index/query calls
without real models or Qdrant."""
from madosho_server.eval import runner, scorer

BASELINE = {
    "corpus": "c",
    "ingest": {"parser": "fake-parser", "chunker": "fake-chunker",
               "embedder": "hash-embedder",
               "store": {"qdrant": {"url": "http://q:6333"}}, "indexes": ["bm25", "dense"]},
    "query": ["keyword_search", "semantic_search", "fuse",
              {"rerank": {"model": "fake-reranker", "top_k": 8}}],
}


def test_apply_candidate_query_side_changes_only_the_op():
    c = {"stage": "rerank", "kind": "query", "op": "rerank",
         "options": {"model": "fake-reranker", "top_k": 3}}
    cfg = runner.apply_candidate(BASELINE, c)
    assert cfg["ingest"] == BASELINE["ingest"]                 # ingest untouched
    rr = [s for s in cfg["query"] if isinstance(s, dict) and "rerank" in s][0]
    assert rr["rerank"]["top_k"] == 3


def test_apply_candidate_ingest_side_changes_the_field():
    c = {"stage": "embed", "kind": "ingest", "field": "embedder", "ref": "bge-small"}
    cfg = runner.apply_candidate(BASELINE, c)
    assert cfg["ingest"]["embedder"] == "bge-small"
    assert cfg["query"] == BASELINE["query"]


def test_ingest_prefix_ignores_query_changes():
    q_cfg = runner.apply_candidate(BASELINE, {"stage": "rerank", "kind": "query",
                                              "op": "rerank", "options": {"model": "fake-reranker", "top_k": 3}})
    assert runner.ingest_prefix(q_cfg) == runner.ingest_prefix(BASELINE)
    e_cfg = runner.apply_candidate(BASELINE, {"stage": "embed", "kind": "ingest",
                                              "field": "embedder", "ref": "bge-small"})
    assert runner.ingest_prefix(e_cfg) != runner.ingest_prefix(BASELINE)


class _FakeCorpus:
    """Records ingest/query calls; returns one hit whose id encodes the collection."""
    def __init__(self, collection):
        self.collection = collection
        self.indexed = 0

    def index_document(self, doc):
        self.indexed += 1

    def query(self, text):
        from madosho.core.types import Chunk, Hit
        ch = Chunk(id="ans", doc_id="d", text="ninety days notice", position=0, page=1)
        return [Hit(chunk_id="ans", score=1.0, source_index="rrf", chunk=ch)]


def _fake_opener_factory():
    opened = []
    def opener(cfg, collection):
        fc = _FakeCorpus(collection)
        opened.append(fc)
        return fc
    return opener, opened


def test_query_side_candidate_reuses_baseline_collection_no_indexing(tmp_path):
    opener, opened = _fake_opener_factory()
    r = runner.StageRunner(BASELINE, run_id=1, corpora_dir=str(tmp_path),
                           parsed_docs={"h1": object()}, opener=opener)
    cand = {"stage": "rerank", "kind": "query", "op": "rerank",
            "options": {"model": "fake-reranker", "top_k": 3}}
    questions = [{"answer_chunk_refs": ["ans"], "source_chunk_text": "ninety days notice"}]
    res = r.run_candidate(cand, questions)
    assert res["post"]["mrr"] == 1.0
    assert all(fc.indexed == 0 for fc in opened)               # no rebuild for query-side
    assert r.ephemeral_collections == []                       # nothing ephemeral created


def test_ingest_candidate_builds_ephemeral_once_then_reuses(tmp_path):
    opener, opened = _fake_opener_factory()
    r = runner.StageRunner(BASELINE, run_id=1, corpora_dir=str(tmp_path),
                           parsed_docs={"h1": object(), "h2": object()}, opener=opener)
    cand = {"stage": "embed", "kind": "ingest", "field": "embedder", "ref": "bge-small"}
    questions = [{"answer_chunk_refs": ["ans"], "source_chunk_text": "ninety days notice"}]
    r.run_candidate(cand, questions)
    r.run_candidate(cand, questions)                            # same candidate again
    built = [fc for fc in opened if fc.indexed > 0]
    assert len(built) == 1                                      # collection built once
    assert built[0].indexed == 2                               # both parsed docs indexed
    assert len(r.ephemeral_collections) == 1


def test_drop_ephemeral_calls_back_for_each_collection(tmp_path):
    opener, _ = _fake_opener_factory()
    dropped = []
    r = runner.StageRunner(BASELINE, run_id=1, corpora_dir=str(tmp_path),
                           parsed_docs={"h1": object()}, opener=opener,
                           drop_collection=lambda name: dropped.append(name))
    cand = {"stage": "chunk", "kind": "ingest", "field": "chunker", "ref": "fixed-window"}
    r.run_candidate(cand, [{"answer_chunk_refs": ["ans"], "source_chunk_text": "x"}])
    r.cleanup()
    assert dropped == r._dropped == [c for c in [*dropped]]     # exactly the ephemeral names
    assert len(dropped) == 1


def test_locking_stacks_changes_into_the_config(tmp_path):
    opener, opened = _fake_opener_factory()
    r = runner.StageRunner(BASELINE, run_id=1, corpora_dir=str(tmp_path),
                           parsed_docs={"h1": object()}, opener=opener)
    r.lock({"stage": "embed", "kind": "ingest", "field": "embedder", "ref": "bge-small"})
    cfg = r._stacked_config({"stage": "rerank", "kind": "query", "op": "rerank",
                             "options": {"model": "fake-reranker", "top_k": 3}})
    assert cfg["ingest"]["embedder"] == "bge-small"            # locked change present
    rr = [s for s in cfg["query"] if isinstance(s, dict) and "rerank" in s][0]
    assert rr["rerank"]["top_k"] == 3                          # plus the new candidate


# ---------------------------------------------------------------------------
# S1: _qdrant_dropper must NOT open a corpus (no ensure_schema / dim check)
# ---------------------------------------------------------------------------

class _FakeQdrantClient:
    """Records constructor kwargs and delete_collection calls."""
    instances: list["_FakeQdrantClient"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.deleted: list[str] = []
        _FakeQdrantClient.instances.append(self)

    def delete_collection(self, name: str):
        self.deleted.append(name)


def test_qdrant_dropper_uses_bare_client_not_corpus_open(monkeypatch):
    """_qdrant_dropper must delete via a bare QdrantClient and never open a corpus."""
    _FakeQdrantClient.instances.clear()

    # Patch QdrantClient inside qdrant_client so the deferred import picks it up
    monkeypatch.setattr("qdrant_client.QdrantClient", _FakeQdrantClient)

    # If open_corpus_from_config is called the test fails immediately
    monkeypatch.setattr("madosho_server.eval.runner.open_corpus_from_config",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("_qdrant_dropper must not open a corpus")))

    drop = runner._qdrant_dropper(".", 1, BASELINE)
    drop("madosho_eval_1_abc")

    assert len(_FakeQdrantClient.instances) == 1, "expected exactly one QdrantClient constructed"
    client = _FakeQdrantClient.instances[0]
    # Built from the baseline store url
    assert client.kwargs.get("url") == "http://q:6333"
    assert client.deleted == ["madosho_eval_1_abc"]


def test_qdrant_dropper_location_mode(monkeypatch):
    """When baseline store uses 'location', the bare client uses location= not url=."""
    _FakeQdrantClient.instances.clear()
    monkeypatch.setattr("qdrant_client.QdrantClient", _FakeQdrantClient)
    monkeypatch.setattr("madosho_server.eval.runner.open_corpus_from_config",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("must not open a corpus")))

    loc_baseline = {
        **BASELINE,
        "ingest": {**BASELINE["ingest"],
                   "store": {"qdrant": {"location": ":memory:"}}},
    }
    drop = runner._qdrant_dropper(".", 1, loc_baseline)
    drop("madosho_eval_1_xyz")

    client = _FakeQdrantClient.instances[0]
    assert client.kwargs.get("location") == ":memory:"
    assert "url" not in client.kwargs
    assert client.deleted == ["madosho_eval_1_xyz"]
