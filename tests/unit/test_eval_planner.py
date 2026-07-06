# tests/unit/test_eval_planner.py
"""Candidate plan. Each candidate is a dict
{stage, label, kind, ...patch} the runner can apply to the baseline config."""
from madosho_server.eval import planner

BASELINE = {
    "corpus": "c",
    "ingest": {"parser": "docling", "chunker": "docling-hybrid",
               "embedder": "granite-embedding-english-r2",
               "store": {"qdrant": {"url": "http://q:6333"}}, "indexes": ["bm25", "dense"]},
    "query": ["keyword_search", "semantic_search", "fuse",
              {"rerank": {"model": "granite-reranker-english-r2"}}],
}

# registry rows shaped like components.list_components() output
REGISTRY = {
    "chunker": [{"name": "docling-hybrid", "origin_tier": "us_src", "hardware": "cpu"},
                {"name": "fixed-window", "origin_tier": "us_src", "hardware": "cpu"},
                {"name": "blocked-model", "origin_tier": "adversarial", "hardware": "cpu"}],
    "embedder": [{"name": "granite-embedding-english-r2", "origin_tier": "us_src", "hardware": "cpu"},
                 {"name": "bge-small", "origin_tier": "us_src", "hardware": "cpu"}],
    "reranker": [{"name": "granite-reranker-english-r2", "origin_tier": "us_src", "hardware": "cpu"}],
}


def test_plan_excludes_the_current_component_and_blocked_tiers():
    plan = planner.build_plan(BASELINE, REGISTRY, traits={})
    chunk_labels = [c["label"] for c in plan["chunk"]]
    # current chunker is not re-proposed; adversarial tier filtered out
    assert not any("docling-hybrid" in lbl for lbl in chunk_labels)
    assert not any("blocked-model" in lbl for lbl in chunk_labels)
    assert any("fixed-window" in lbl for lbl in chunk_labels)


def test_chunk_and_embed_candidates_are_ingest_kind():
    plan = planner.build_plan(BASELINE, REGISTRY, traits={})
    assert all(c["kind"] == "ingest" and c["field"] == "chunker" for c in plan["chunk"])
    assert all(c["kind"] == "ingest" and c["field"] == "embedder" for c in plan["embed"])


def test_query_side_candidates_are_query_kind():
    plan = planner.build_plan(BASELINE, REGISTRY, traits={})
    assert all(c["kind"] == "query" for c in plan["semantic"])
    assert all(c["kind"] == "query" for c in plan["keyword"])
    assert all(c["kind"] == "query" and c["op"] == "rerank" for c in plan["rerank"])
    # semantic candidates vary the dense leg's k
    assert any(c["options"].get("k") for c in plan["semantic"])


def test_extraction_is_not_swept():
    plan = planner.build_plan(BASELINE, REGISTRY, traits={})
    assert "extraction" not in plan


def test_plan_has_all_swept_stages():
    plan = planner.build_plan(BASELINE, REGISTRY, traits={})
    assert set(plan) == {"chunk", "embed", "keyword", "semantic", "rerank"}
