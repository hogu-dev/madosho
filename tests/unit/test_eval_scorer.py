# tests/unit/test_eval_scorer.py
"""Retrieval metrics. A retrieved chunk is relevant if its id is an
answer ref (query-side candidates keep baseline ids) OR its text overlaps the
source chunk (chunker swaps change ids, so we fall back to content overlap)."""
from madosho_server.eval import scorer


def _hit(cid, text=""):
    return {"id": cid, "text": text}


def test_is_relevant_by_id():
    q = {"answer_chunk_refs": ["c2"], "source_chunk_text": "irrelevant text"}
    assert scorer.is_relevant(_hit("c2"), q)
    assert not scorer.is_relevant(_hit("c9"), q)


def test_is_relevant_by_text_overlap_when_ids_differ():
    # chunker swap: ids changed, but the retrieved chunk covers the answer text
    q = {"answer_chunk_refs": ["c2"], "source_chunk_text": "ninety days written notice"}
    assert scorer.is_relevant(_hit("zz", "the clause requires ninety days written notice to quit"), q)
    assert not scorer.is_relevant(_hit("zz", "payment terms are net thirty"), q)


def test_hit_at_k_is_one_if_a_relevant_chunk_is_in_top_k():
    q = {"answer_chunk_refs": ["c3"], "source_chunk_text": ""}
    retrieved = [_hit("c1"), _hit("c2"), _hit("c3"), _hit("c4")]
    assert scorer.hit_at_k(retrieved, q, 3) == 1.0   # c3 at rank 3
    assert scorer.hit_at_k(retrieved, q, 2) == 0.0   # not in top 2


def test_mrr_is_reciprocal_of_first_relevant_rank():
    q = {"answer_chunk_refs": ["c3"], "source_chunk_text": ""}
    retrieved = [_hit("c1"), _hit("c2"), _hit("c3")]
    assert scorer.mrr_one(retrieved, q) == 1 / 3
    assert scorer.mrr_one([_hit("c3")], q) == 1.0
    assert scorer.mrr_one([_hit("c1")], q) == 0.0


def test_ndcg_at_k_binary_gain():
    q = {"answer_chunk_refs": ["c2"], "source_chunk_text": ""}
    # one relevant doc at rank 2 -> DCG = 1/log2(3); ideal IDCG = 1/log2(2) = 1
    import math
    got = scorer.ndcg_at_k([_hit("c1"), _hit("c2"), _hit("c3")], q, 5)
    assert abs(got - (1 / math.log2(3))) < 1e-9


def test_score_run_aggregates_across_questions():
    questions = [
        {"answer_chunk_refs": ["a"], "source_chunk_text": ""},
        {"answer_chunk_refs": ["b"], "source_chunk_text": ""},
    ]
    per_q_hits = [
        [_hit("a"), _hit("x")],          # rank 1 -> mrr 1.0, hit@1 1.0
        [_hit("y"), _hit("b")],          # rank 2 -> mrr 0.5, hit@1 0.0, hit@3 1.0
    ]
    out = scorer.score_run(per_q_hits, questions, ks=(1, 3))
    assert out["mrr"] == 0.75
    assert out["hit@1"] == 0.5
    assert out["hit@3"] == 1.0
    assert out["n"] == 2


def test_score_run_empty_is_zero():
    out = scorer.score_run([], [], ks=(1, 5))
    assert out["mrr"] == 0.0 and out["hit@5"] == 0.0 and out["n"] == 0
