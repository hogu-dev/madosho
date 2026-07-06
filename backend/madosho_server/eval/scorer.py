# backend/madosho_server/eval/scorer.py
"""Objective retrieval metrics (no LLM). A question carries the ground-truth
answer chunk(s); a candidate pipeline's retrieval is scored against them.

Relevance is intentionally chunker-invariant: when F swaps the chunker the chunk
ids change, so id equality alone would wrongly score every chunker candidate as a
total miss. We therefore also accept a retrieved chunk whose *text* covers the
answer's source text. Alternative considered: match on (doc_id, page) only - too
coarse, a whole page is rarely a precise answer. Token-Jaccard + substring is the
cheapest predicate that survives re-chunking without an LLM judge."""
from __future__ import annotations

import math

DEFAULT_KS = (1, 3, 5, 10)
PRIMARY_METRIC = "mrr"
REL_JACCARD = 0.6          # tunable: min token-overlap to call a re-chunked hit relevant


def _norm_tokens(text: str) -> set[str]:
    return set((text or "").lower().split())


def is_relevant(chunk: dict, question: dict) -> bool:
    if chunk.get("id") in (question.get("answer_chunk_refs") or []):
        return True
    answer = " ".join((question.get("source_chunk_text") or "").lower().split())
    if not answer:
        return False
    got = " ".join((chunk.get("text") or "").lower().split())
    if answer in got:
        return True
    a, b = _norm_tokens(answer), _norm_tokens(got)
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= REL_JACCARD


def _first_relevant_rank(retrieved: list[dict], question: dict) -> int | None:
    for i, c in enumerate(retrieved):
        if is_relevant(c, question):
            return i + 1     # 1-indexed rank
    return None


def hit_at_k(retrieved: list[dict], question: dict, k: int) -> float:
    rank = _first_relevant_rank(retrieved[:k], question)
    return 1.0 if rank is not None else 0.0


def mrr_one(retrieved: list[dict], question: dict) -> float:
    rank = _first_relevant_rank(retrieved, question)
    return 1.0 / rank if rank is not None else 0.0


def ndcg_at_k(retrieved: list[dict], question: dict, k: int) -> float:
    # binary relevance, single relevant target -> IDCG = 1 (best case rank 1)
    for i, c in enumerate(retrieved[:k]):
        if is_relevant(c, question):
            return 1.0 / math.log2(i + 2)   # rank i+1 -> log2(rank+1)
    return 0.0


def score_run(per_question_hits: list[list[dict]], questions: list[dict],
              ks: tuple[int, ...] = DEFAULT_KS) -> dict:
    """Aggregate metrics across all questions. per_question_hits[i] is the ordered
    retrieved-chunk list for questions[i]."""
    n = len(questions)
    if n == 0:
        out = {f"hit@{k}": 0.0 for k in ks}
        out.update({"mrr": 0.0, "ndcg@5": 0.0, "n": 0})
        return out
    out = {}
    for k in ks:
        out[f"hit@{k}"] = round(sum(hit_at_k(h, q, k) for h, q in zip(per_question_hits, questions)) / n, 4)
    out["mrr"] = round(sum(mrr_one(h, q) for h, q in zip(per_question_hits, questions)) / n, 4)
    out["ndcg@5"] = round(sum(ndcg_at_k(h, q, 5) for h, q in zip(per_question_hits, questions)) / n, 4)
    out["n"] = n
    return out
