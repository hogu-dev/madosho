"""sparse.py is stdlib-only — these run in the fast suite without qdrant-client."""
from madosho.adapters.qdrant.sparse import encode_document, encode_query


def test_document_encoding_is_deterministic():
    assert encode_document("the termination clause") == \
        encode_document("the termination clause")


def test_query_and_document_share_token_indices():
    d_idx, _ = encode_document("termination clause requires notice")
    q_idx, q_val = encode_query("termination notice")
    assert set(q_idx) <= set(d_idx)
    assert q_val == [1.0] * len(q_idx)


def test_query_indices_are_unique_and_sorted():
    idx, _ = encode_query("notice notice termination notice")
    assert idx == sorted(set(idx)) and len(idx) == 2


def test_tf_saturates_but_repeated_terms_score_higher():
    one_idx, one_val = encode_document("termination")
    many_idx, many_val = encode_document(" ".join(["termination"] * 50))
    tok = one_idx[0]
    assert many_idx == [tok]
    assert one_val[0] < many_val[0] < 2.2   # monotone, bounded by k1+1


def test_empty_and_punctuation_only_inputs():
    assert encode_document("") == ([], [])
    assert encode_query("...!!!") == ([], [])


def test_tokenization_lowercases_and_splits_alnum():
    a, _ = encode_document("Termination-Clause")
    b, _ = encode_document("termination clause")
    assert set(a) == set(b)
