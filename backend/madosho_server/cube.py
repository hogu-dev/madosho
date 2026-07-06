# backend/madosho_server/cube.py
"""Read-side aggregation of technique_rating rows into the per-pipeline cube.

Pure function over rows + a small pipeline-metadata map. The page compares the
named pipelines on a document, so the cube is grouped one document group per
document, each holding:

  - a per-document RETRIEVAL strip (keyword/semantic/rerank) -- these are not
    per-pipeline today (they live corpus- or document-level), so they sit on the
    document, shared across its pipelines; and
  - one row per pipeline carrying the BUILD dims (extraction/chunk/embed), which
    DO vary per pipeline (keyed by candidate_config = pipeline name).

For each (pipeline, build-dim) and (document, retrieval-dim) it keeps the
highest-precedence cell (human > measured > f-empirical > static). Corpus-level
retrieval rows (document_id=None) overlay every document's strip. Build/retrieval
totals are weighted averages renormalized over the dims actually present -- the
same math the old per-document Total used, just split by dim group.
"""
from __future__ import annotations

BUILD_DIMENSIONS = ("extraction", "chunk", "embed")
RETRIEVAL_DIMENSIONS = ("keyword", "semantic", "rerank")
ALL_DIMENSIONS = BUILD_DIMENSIONS + RETRIEVAL_DIMENSIONS

# Foundational stages weigh more; tunable per corpus later. Sums to 1.0.
DEFAULT_WEIGHTS = {"extraction": 0.30, "embed": 0.20, "semantic": 0.20,
                   "rerank": 0.15, "chunk": 0.08, "keyword": 0.07}

_PRECEDENCE = {"static": 0, "f-empirical": 1, "measured": 2, "human": 3}


def _pick(rows: list[dict]) -> dict:
    return max(rows, key=lambda r: _PRECEDENCE.get(r["source"], 0))


def _total(cells: dict, weights: dict, dims=ALL_DIMENSIONS) -> float:
    """Weighted average over the given dims, renormalized over those present."""
    num = sum(weights[d] * cells[d]["score"] for d in dims if d in cells)
    den = sum(weights[d] for d in dims if d in cells)
    return round(num / den, 1) if den else 0.0


def _cell(r: dict) -> dict:
    return {"score": r["score"], "source": r["source"],
            "rationale": r.get("rationale"), "suggestion": r.get("suggestion")}


def _pick_cells(by_dim: dict[str, list[dict]], dims) -> dict:
    """Highest-precedence cell per present dim, restricted to `dims`."""
    return {d: _cell(_pick(by_dim[d])) for d in dims if d in by_dim}


def assemble_cube(rows: list[dict], pipeline_meta: dict[int, list[dict]],
                  weights: dict | None = None) -> dict:
    """Group rating rows into per-document, per-pipeline shape.

    rows: dicts with document_id, dimension, score, source, candidate_config,
      rationale, suggestion. Build-dim rows carry candidate_config = pipeline
      name; retrieval-dim rows carry candidate_config = None (document- or
      corpus-level).
    pipeline_meta: {document_id: [{"name", "pipeline_id", "effective"}, ...]}
      in display order. Drives which documents/rows appear and the effective tag.
    """
    weights = weights or DEFAULT_WEIGHTS

    # Build rows -> grouped by (document_id, pipeline name) -> dim -> [rows].
    by_pipe: dict[tuple[int, str], dict[str, list[dict]]] = {}
    # Retrieval rows -> per-document strip, plus a corpus-level overlay.
    retr_by_doc: dict[int, dict[str, list[dict]]] = {}
    corpus_retr: dict[str, list[dict]] = {}
    for r in rows:
        dim = r["dimension"]
        if dim in BUILD_DIMENSIONS:
            if r["document_id"] is None:
                continue                       # build dims are always doc-scoped
            key = (r["document_id"], r.get("candidate_config"))
            by_pipe.setdefault(key, {}).setdefault(dim, []).append(r)
        elif dim in RETRIEVAL_DIMENSIONS:
            if r["document_id"] is None:
                corpus_retr.setdefault(dim, []).append(r)
            else:
                retr_by_doc.setdefault(r["document_id"], {}).setdefault(dim, []).append(r)

    documents = []
    for doc_id in sorted(pipeline_meta):
        pipelines = []
        for p in pipeline_meta[doc_id]:
            cells = _pick_cells(by_pipe.get((doc_id, p["name"]), {}), BUILD_DIMENSIONS)
            pipelines.append({
                "name": p["name"], "pipeline_id": p["pipeline_id"],
                "effective": p["effective"], "cells": cells,
                "build_total": _total(cells, weights, BUILD_DIMENSIONS),
            })

        # Retrieval strip: this document's own rows, overlaid by corpus-level rows
        # (higher precedence wins; corpus rows are shared across all documents).
        retr = _pick_cells(retr_by_doc.get(doc_id, {}), RETRIEVAL_DIMENSIONS)
        for dim, rs in corpus_retr.items():
            picked = _pick(rs)
            existing = retr.get(dim)
            if existing is None or _PRECEDENCE.get(picked["source"], 0) >= \
                    _PRECEDENCE.get(existing["source"], 0):
                retr[dim] = _cell(picked)

        documents.append({
            "document_id": doc_id,
            "retrieval": retr,
            "retrieval_total": _total(retr, weights, RETRIEVAL_DIMENSIONS),
            "pipelines": pipelines,
        })

    return {"documents": documents, "weights": weights}
