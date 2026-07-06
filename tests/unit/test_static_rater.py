# tests/unit/test_static_rater.py
from madosho_server.static_rater import rate_static, STATIC_DIMENSIONS, RATER_VERSION


def _by_dim(rows):
    return {r["dimension"]: r for r in rows}


def test_rates_all_six_dimensions():
    rows = rate_static({"page_count": 2, "chunk_count": 4, "table_count": 0,
                        "avg_chunk_chars": 800.0, "text_density": 1600.0, "table_density": 0.0})
    assert {r["dimension"] for r in rows} == set(STATIC_DIMENSIONS)
    assert all(0.0 <= r["score"] <= 5.0 for r in rows)
    assert all(r["source"] == "static" and r["rater_version"] == RATER_VERSION for r in rows)


def test_clean_dense_doc_scores_extraction_high_no_suggestion():
    rows = _by_dim(rate_static({"page_count": 2, "chunk_count": 4, "table_count": 0,
                                "avg_chunk_chars": 800.0, "text_density": 1800.0, "table_density": 0.0}))
    assert rows["extraction"]["score"] >= 4.0
    assert rows["extraction"]["suggestion"] is None


def test_scanned_doc_scores_extraction_low_with_vision_suggestion():
    rows = _by_dim(rate_static({"page_count": 3, "chunk_count": 3, "table_count": 0,
                                "avg_chunk_chars": 40.0, "text_density": 120.0, "table_density": 0.0}))
    assert rows["extraction"]["score"] <= 2.5
    assert "vision" in rows["extraction"]["suggestion"].lower()


def test_small_chunks_suggest_larger():
    rows = _by_dim(rate_static({"page_count": 1, "chunk_count": 9, "table_count": 0,
                                "avg_chunk_chars": 120.0, "text_density": 1080.0, "table_density": 0.0}))
    assert rows["chunk"]["score"] <= 3.0
    assert "chunk" in rows["chunk"]["suggestion"].lower()
