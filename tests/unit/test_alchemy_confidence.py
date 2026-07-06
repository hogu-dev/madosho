import types

from alchemy.confidence import blend_confidence, split_grade_marker


def _cit(doc_id):
    return types.SimpleNamespace(document_id=doc_id)


def test_split_strips_trailing_marker():
    content, grade = split_grade_marker("Some prose.\n\nCONFIDENCE: high\n")
    assert content == "Some prose."
    assert grade == "high"


def test_split_is_case_insensitive_and_tolerant():
    content, grade = split_grade_marker("body\n  confidence:  Medium  ")
    assert content == "body"
    assert grade == "medium"


def test_split_no_marker_returns_none():
    content, grade = split_grade_marker("just a section body")
    assert content == "just a section body"
    assert grade is None


def test_split_marker_mid_text_is_not_stripped():
    text = "CONFIDENCE: high\nreal body after"
    content, grade = split_grade_marker(text)
    assert content == text
    assert grade is None


def test_blend_zero_docs_caps_at_low():
    c = blend_confidence("high", [])
    assert c == {"level": "low", "self_grade": "high",
                 "distinct_docs": 0, "citations": 0}


def test_blend_one_doc_caps_at_medium():
    c = blend_confidence("high", [_cit(1), _cit(1)])
    assert c["level"] == "medium"
    assert c["distinct_docs"] == 1
    assert c["citations"] == 2


def test_blend_two_docs_allows_high():
    assert blend_confidence("high", [_cit(1), _cit(2)])["level"] == "high"


def test_blend_self_grade_can_only_lower():
    assert blend_confidence("low", [_cit(1), _cit(2)])["level"] == "low"


def test_blend_missing_grade_defaults_neutral():
    # no self-grade: treat as medium, still capped by facts
    assert blend_confidence(None, [_cit(1), _cit(2)])["level"] == "medium"
    assert blend_confidence(None, [])["level"] == "low"


def test_blend_ignores_anonymous_citations_for_docs():
    c = blend_confidence("high", [_cit(None), _cit(3)])
    assert c["distinct_docs"] == 1
    assert c["citations"] == 2
