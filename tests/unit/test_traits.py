# tests/unit/test_traits.py
from madosho_server.traits import extract_traits


def test_empty_artifacts_safe_defaults():
    t = extract_traits({})
    assert t["page_count"] == 1 and t["chunk_count"] == 0 and t["avg_chunk_chars"] == 0.0

def test_dense_clean_doc():
    artifacts = {
        "chunks": [{"text": "x" * 1800, "page": 0}, {"text": "y" * 1800, "page": 1}],
        "blocks": [{"kind": "table", "provenance": {"page": 1}}],
    }
    t = extract_traits(artifacts)
    assert t["page_count"] == 2
    assert t["chunk_count"] == 2
    assert t["table_count"] == 1
    assert t["avg_chunk_chars"] == 1800.0
    assert t["text_density"] == 1800.0          # 3600 chars / 2 pages
    assert t["table_density"] == 0.5            # 1 table / 2 pages

def test_sparse_scanned_like_doc():
    artifacts = {"chunks": [{"text": "noisy ocr", "page": 0}], "blocks": []}
    t = extract_traits(artifacts)
    assert t["text_density"] < 200              # triggers low-extraction rules downstream
