# tests/unit/test_cube.py
"""Unit tests for the per-pipeline split cube (assemble_cube).

The cube groups rows into one document group per document, each carrying a
per-document retrieval strip (keyword/semantic/rerank) and one row per pipeline
(extraction/chunk/embed). Build totals renormalize over the present build dims;
the retrieval total over the present retrieval dims -- same weighted math the
page used before, just split by which dims are per-pipeline vs per-document.
"""
import pytest
from madosho_server.cube import (
    assemble_cube, DEFAULT_WEIGHTS, BUILD_DIMENSIONS, RETRIEVAL_DIMENSIONS, _total,
)


def _row(doc, dim, score, source="static", cfg=None):
    return {"document_id": doc, "dimension": dim, "score": score, "source": source,
            "candidate_config": cfg, "rationale": None, "suggestion": None}


def _build_rows(doc, name, scores, source="static"):
    """One row per build dim for pipeline `name` on document `doc`."""
    return [_row(doc, dim, scores[dim], source, cfg=name) for dim in BUILD_DIMENSIONS]


def _retrieval_rows(doc, scores, source="static"):
    """Per-document retrieval rows (candidate_config=None)."""
    return [_row(doc, dim, scores[dim], source) for dim in RETRIEVAL_DIMENSIONS]


def _meta(*names, effective=None):
    """pipeline_meta list for one document from pipeline names in id order."""
    return [{"name": n, "pipeline_id": i + 1, "effective": (n == effective)}
            for i, n in enumerate(names)]


# --- shape + grouping -------------------------------------------------------

def test_one_row_per_pipeline_grouped_under_document():
    rows = (_build_rows(1, "p_a", {"extraction": 3.5, "chunk": 4, "embed": 4}) +
            _build_rows(1, "p_b", {"extraction": 3.5, "chunk": 3, "embed": 4}))
    cube = assemble_cube(rows, {1: _meta("p_a", "p_b", effective="p_a")})
    docs = cube["documents"]
    assert len(docs) == 1 and docs[0]["document_id"] == 1
    names = [p["name"] for p in docs[0]["pipelines"]]
    assert names == ["p_a", "p_b"]                     # preserves meta (id) order


def test_pipeline_order_follows_meta_not_rows():
    # rows arrive p_b first, but meta lists p_a then p_b -> output follows meta.
    rows = (_build_rows(1, "p_b", {"extraction": 3, "chunk": 3, "embed": 3}) +
            _build_rows(1, "p_a", {"extraction": 4, "chunk": 4, "embed": 4}))
    cube = assemble_cube(rows, {1: _meta("p_a", "p_b")})
    assert [p["name"] for p in cube["documents"][0]["pipelines"]] == ["p_a", "p_b"]


def test_build_dims_ride_pipeline_rows_retrieval_dims_do_not():
    rows = (_build_rows(1, "p_a", {"extraction": 4, "chunk": 4, "embed": 4}) +
            _retrieval_rows(1, {"keyword": 3.5, "semantic": 3.8, "rerank": 3.5}))
    doc = assemble_cube(rows, {1: _meta("p_a")})["documents"][0]
    pcells = doc["pipelines"][0]["cells"]
    assert set(pcells) == set(BUILD_DIMENSIONS)            # only build dims on the row
    assert set(doc["retrieval"]) == set(RETRIEVAL_DIMENSIONS)  # retrieval on the doc strip


# --- totals -----------------------------------------------------------------

def test_build_total_is_weighted_average_over_build_dims():
    rows = _build_rows(1, "p_a", {"extraction": 3.5, "chunk": 4, "embed": 4})
    doc = assemble_cube(rows, {1: _meta("p_a")})["documents"][0]
    # matches the mockup's F-16 docling Build score
    assert doc["pipelines"][0]["build_total"] == pytest.approx(3.7, abs=0.05)


def test_retrieval_total_is_weighted_average_over_retrieval_dims():
    rows = _retrieval_rows(1, {"keyword": 3.5, "semantic": 3.8, "rerank": 3.5})
    doc = assemble_cube(rows, {1: _meta("p_a")})["documents"][0]
    expected = _total({d: {"score": s} for d, s in
                       (("keyword", 3.5), ("semantic", 3.8), ("rerank", 3.5))},
                      DEFAULT_WEIGHTS, RETRIEVAL_DIMENSIONS)
    assert doc["retrieval_total"] == pytest.approx(expected, abs=0.001)


def test_totals_renormalize_over_present_dims_only():
    # only two of the three build dims present -> denominator excludes the missing one
    rows = [_row(1, "extraction", 4, cfg="p_a"), _row(1, "embed", 2, cfg="p_a")]
    doc = assemble_cube(rows, {1: _meta("p_a")})["documents"][0]
    w = DEFAULT_WEIGHTS
    expected = round((w["extraction"] * 4 + w["embed"] * 2) / (w["extraction"] + w["embed"]), 1)
    assert doc["pipelines"][0]["build_total"] == pytest.approx(expected)


# --- precedence + effective -------------------------------------------------

def test_measured_beats_static_per_pipeline_cell():
    rows = _build_rows(1, "p_a", {"extraction": 3, "chunk": 3, "embed": 3})
    rows.append(_row(1, "extraction", 4.5, source="measured", cfg="p_a"))
    cell = assemble_cube(rows, {1: _meta("p_a")})["documents"][0]["pipelines"][0]["cells"]["extraction"]
    assert cell["score"] == 4.5 and cell["source"] == "measured"


def test_effective_flag_carried_through():
    rows = (_build_rows(1, "p_a", {"extraction": 3, "chunk": 3, "embed": 3}) +
            _build_rows(1, "p_b", {"extraction": 3, "chunk": 3, "embed": 3}))
    pipes = assemble_cube(rows, {1: _meta("p_a", "p_b", effective="p_b")})["documents"][0]["pipelines"]
    flags = {p["name"]: p["effective"] for p in pipes}
    assert flags == {"p_a": False, "p_b": True}


def test_pipeline_with_no_ratings_is_an_empty_row():
    # a built-but-unrated (or still-indexing) pipeline shows a row with no cells.
    rows = _build_rows(1, "p_a", {"extraction": 4, "chunk": 4, "embed": 4})
    pipes = assemble_cube(rows, {1: _meta("p_a", "p_new")})["documents"][0]["pipelines"]
    new = next(p for p in pipes if p["name"] == "p_new")
    assert new["cells"] == {} and new["build_total"] == 0.0


# --- retrieval: per-doc + corpus-level overlay ------------------------------

def test_corpus_level_retrieval_attaches_to_every_document():
    # corpus-wide retrieval rows (document_id=None) apply identically to each doc.
    rows = (_build_rows(1, "p1", {"extraction": 3, "chunk": 3, "embed": 3}) +
            _build_rows(2, "p2", {"extraction": 3, "chunk": 3, "embed": 3}) +
            [_row(None, dim, 3.5, source="f-empirical")
             for dim in RETRIEVAL_DIMENSIONS])
    cube = assemble_cube(rows, {1: _meta("p1"), 2: _meta("p2")})
    for doc in cube["documents"]:
        assert doc["retrieval"]["semantic"]["score"] == pytest.approx(3.5)
        assert doc["retrieval"]["semantic"]["source"] == "f-empirical"


def test_per_document_retrieval_overrides_lands_on_right_group():
    rows = (_build_rows(1, "p1", {"extraction": 3, "chunk": 3, "embed": 3}) +
            _build_rows(2, "p2", {"extraction": 3, "chunk": 3, "embed": 3}) +
            _retrieval_rows(1, {"keyword": 2.0, "semantic": 2.0, "rerank": 2.0}) +
            _retrieval_rows(2, {"keyword": 4.0, "semantic": 4.0, "rerank": 4.0}))
    cube = assemble_cube(rows, {1: _meta("p1"), 2: _meta("p2")})
    by_id = {d["document_id"]: d for d in cube["documents"]}
    assert by_id[1]["retrieval"]["keyword"]["score"] == pytest.approx(2.0)
    assert by_id[2]["retrieval"]["keyword"]["score"] == pytest.approx(4.0)


def test_corpus_level_retrieval_overlays_per_doc_by_precedence():
    # doc-level static retrieval + higher-precedence corpus-level row -> corpus wins.
    rows = (_build_rows(1, "p1", {"extraction": 3, "chunk": 3, "embed": 3}) +
            _retrieval_rows(1, {"keyword": 2.0, "semantic": 2.0, "rerank": 2.0},
                            source="static") +
            [_row(None, "semantic", 4.5, source="measured")])
    doc = assemble_cube(rows, {1: _meta("p1")})["documents"][0]
    assert doc["retrieval"]["semantic"]["score"] == pytest.approx(4.5)
    assert doc["retrieval"]["semantic"]["source"] == "measured"
    assert doc["retrieval"]["keyword"]["score"] == pytest.approx(2.0)   # untouched


# --- edges ------------------------------------------------------------------

def test_empty_corpus_no_pipelines():
    assert assemble_cube([], {})["documents"] == []


def test_weights_echoed_back():
    cube = assemble_cube([], {})
    assert cube["weights"] == DEFAULT_WEIGHTS
