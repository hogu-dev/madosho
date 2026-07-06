# tests/unit/test_textdiff.py
from madosho_server.textdiff import diff_spans, divergence_spans


def test_identical_texts_have_no_spans():
    assert diff_spans("same text here", "same text here") == {"a": [], "b": []}


def test_single_word_replacement_marks_each_side():
    a, b = "the quick brown fox", "the slow brown fox"
    spans = diff_spans(a, b)
    assert spans["a"] == [[4, 9]]      # "quick"
    assert spans["b"] == [[4, 8]]      # "slow"
    assert a[4:9] == "quick" and b[4:8] == "slow"


def test_insertion_only_marks_b():
    spans = diff_spans("alpha gamma", "alpha beta gamma")
    assert spans["a"] == []
    assert spans["b"] and "beta" in "alpha beta gamma"[spans["b"][0][0]:spans["b"][0][1]]


def test_whitespace_only_differences_are_ignored():
    # extra blank lines, re-wrapping, and changed indentation all differ only in
    # whitespace -> no disagreement spans on either side.
    a = "the quick brown fox"
    b = "the   quick\n\n  brown\tfox"
    assert diff_spans(a, b) == {"a": [], "b": []}


def test_content_change_still_flagged_despite_whitespace_noise():
    # a real word change surrounded by whitespace churn still marks only the word.
    a = "the quick brown fox"
    b = "the\nslow\n\nbrown   fox"
    spans = diff_spans(a, b)
    assert a[spans["a"][0][0]:spans["a"][0][1]] == "quick"
    assert b[spans["b"][0][0]:spans["b"][0][1]] == "slow"


# ---- N-way divergence (union of pairwise diffs) --------------------------
# divergence_spans generalises the 2-way diff to any number of texts with a
# single "highlighted = these do not all agree here" flag per column. No
# baseline: a span is highlighted in column i when it differs from >=1 other.

def test_divergence_all_identical_has_no_spans():
    assert divergence_spans(["same text", "same text", "same text"]) == [[], [], []]


def test_divergence_single_text_has_no_spans():
    # nothing to disagree with -> no highlight.
    assert divergence_spans(["only one"]) == [[]]


def test_divergence_empty_input():
    assert divergence_spans([]) == []


def test_divergence_marks_the_disagreeing_locus_in_every_column():
    # columns 0 and 1 agree on "quick" but both still differ from column 2's
    # "slow" -> the locus is flagged in ALL three columns (symmetric, no baseline).
    texts = ["the quick brown fox", "the quick brown fox", "the slow brown fox"]
    cols = divergence_spans(texts)
    assert texts[0][cols[0][0][0]:cols[0][0][1]] == "quick"
    assert texts[1][cols[1][0][0]:cols[1][0][1]] == "quick"
    assert texts[2][cols[2][0][0]:cols[2][0][1]] == "slow"


def test_divergence_unions_differences_against_multiple_others():
    # column 0 differs from col1 at "a" and from col2 at "c" -> BOTH loci flagged
    # on column 0 (union of its pairwise diffs, merged).
    texts = ["x a y c z", "x B y c z", "x a y C z"]
    cols = divergence_spans(texts)
    got = [texts[0][s:e] for s, e in cols[0]]
    assert "a" in got and "c" in got


def test_divergence_ignores_whitespace_only_noise():
    # inherits diff_spans' whitespace-insensitivity -> re-wrapping is not divergence.
    texts = ["the quick brown fox", "the   quick\n\nbrown\tfox"]
    assert divergence_spans(texts) == [[], []]
