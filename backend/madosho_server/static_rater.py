# backend/madosho_server/static_rater.py
"""Rule-based v1 rater: document traits -> a 0-5 suitability score per stage.

Deterministic and free (no LLM), so the cube is fully populated the moment a
document finishes indexing. Each rule returns (score, rationale, suggestion);
`rater_version` stamps the ruleset so re-rates are traceable. An LLM-written
rater is a later swap that reuses the same row shape.
"""
from __future__ import annotations

STATIC_DIMENSIONS = ("extraction", "chunk", "embed", "keyword", "semantic", "rerank")
RATER_VERSION = "static-v1"


def _extraction(t):     # text per page is the main signal for extraction quality
    d = t["text_density"]
    if d >= 1500: return 4.5, "Dense, clean text extracted per page.", None
    if d >= 600:  return 3.5, "Moderate text extracted per page.", None
    if d >= 200:  return 2.5, "Sparse text per page; likely scanned or image-heavy.", \
                         "Run the extraction comparison; the vision converter may win."
    return 1.5, "Very little text per page; probably scanned.", \
           "Run the extraction comparison; the vision converter likely wins."


def _chunk(t):          # healthy chunk band keeps retrieval focused
    a = t["avg_chunk_chars"]
    if a == 0:          return 1.0, "No chunks were produced.", "Re-ingest; extraction may have failed."
    if a < 300:         return 2.5, "Chunks are small; context may fragment.", \
                               "Increase chunk size or merge adjacent chunks."
    if a > 1200:        return 3.0, "Chunks are large; relevance may dilute.", \
                               "Reduce chunk size for finer retrieval."
    return 4.0, "Chunk sizes sit in a healthy band.", None


def _embed(t):
    d = t["text_density"]
    if d >= 1000: return 4.0, "Clean text embeds well.", None
    if d >= 300:  return 3.0, "Some noise may weaken embeddings.", None
    return 2.0, "Sparse/noisy text weakens dense embeddings.", "A layout-aware embedder may help."


def _keyword(t):
    d = t["text_density"]
    if d >= 800: return 3.5, "Enough text for solid keyword recall.", None
    if d >= 250: return 2.8, "Limited text for keyword matching.", None
    return 2.0, "Sparse text limits keyword search.", None


def _semantic(t):
    d = t["text_density"]
    if d >= 1000: return 3.8, "Clean passages support semantic search.", None
    if d >= 300:  return 3.0, "Mixed text quality for semantic search.", None
    return 2.2, "Sparse text weakens semantic retrieval.", None


def _rerank(t):
    n = t["chunk_count"]
    if n >= 5: return 3.5, "Enough candidates for reranking to help.", None
    if n >= 1: return 3.0, "Few candidates; reranking has limited effect.", None
    return 1.0, "No candidates to rerank.", None


_RULES = {"extraction": _extraction, "chunk": _chunk, "embed": _embed,
          "keyword": _keyword, "semantic": _semantic, "rerank": _rerank}


def rate_static(traits: dict) -> list[dict]:
    """Return one rating row per static dimension (source='static')."""
    rows = []
    for dim in STATIC_DIMENSIONS:
        score, rationale, suggestion = _RULES[dim](traits)
        rows.append({"dimension": dim, "score": float(score), "source": "static",
                     "rationale": rationale, "suggestion": suggestion,
                     "rater_version": RATER_VERSION, "candidate_config": None})
    return rows
