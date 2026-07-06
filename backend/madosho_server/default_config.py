from __future__ import annotations


def default_pipeline_config(corpus_name: str, qdrant_url: str) -> dict:
    """The built-in recipe a new corpus gets so `POST /corpora` just works.

    Tier B default stack (docling -> granite -> qdrant), no `source` (the
    service pushes files in one at a time), and the C hybrid query stack
    (keyword_search + semantic_search → fuse RRF → granite reranker). The
    Qdrant collection defaults to 'madosho_<corpus>' inside the store adapter."""
    return {
        "corpus": corpus_name,
        "ingest": {
            "parser": "docling",
            "chunker": "docling-hybrid",
            "embedder": "granite-embedding-english-r2",
            "store": {"qdrant": {"url": qdrant_url}},
            "indexes": ["bm25", "dense"],
        },
        "query": [
            "keyword_search",
            "semantic_search",
            "fuse",
            {"rerank": {"model": "granite-reranker-english-r2"}},
        ],
    }
