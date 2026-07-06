# backend/madosho_server/eval/golden.py
"""Grounded synthetic Q/A. For a sampled, critic-approved chunk, the LLM writes a
question answerable from THAT chunk, and the chunk becomes the ground-truth answer
key. This is the only LLM spend in a run (candidate sweeps are embed + search
only). The `llm` argument is a `str -> str` callable so tests inject a fake and
production passes a thin wrapper over madosho_server.llm.complete.

Critic filter: a cheap, deterministic rule that drops chunks too short or too
generic to anchor a specific question (headers, page numbers, boilerplate). A
heavier LLM critic is a later swap behind the same is_useful_chunk seam."""
from __future__ import annotations

from collections import defaultdict

MIN_USEFUL_CHARS = 40          # tunable: below this a chunk rarely anchors a specific Q
QUESTION_PROMPT = (
    "Write one specific question that is answered by the passage below. Reply with "
    "the question only, no preamble.\n\nPassage:\n{text}\n")


def is_useful_chunk(chunk: dict) -> bool:
    text = (chunk.get("text") or "").strip()
    if len(text) < MIN_USEFUL_CHARS:
        return False
    # crude generic-ness guard: needs several distinct words
    return len(set(text.lower().split())) >= 8


def stratified_sample(docs: list[dict], n: int) -> list[dict]:
    """Spread the sample across document types (traits.doc_type) so the golden set
    is not dominated by one kind. Round-robins strata until n are chosen."""
    strata: dict[str, list[dict]] = defaultdict(list)
    for d in docs:
        strata[(d.get("traits") or {}).get("doc_type", "unknown")].append(d)
    order = sorted(strata)
    picked: list[dict] = []
    i = 0
    while len(picked) < n and any(strata[s] for s in order):
        bucket = strata[order[i % len(order)]]
        if bucket:
            picked.append(bucket.pop(0))
        i += 1
    return picked


def generate_for_chunk(chunk: dict, document_id: int, llm) -> dict:
    question = llm(QUESTION_PROMPT.format(text=chunk["text"])).strip()
    return {"document_id": document_id, "question": question,
            "answer_chunk_refs": [chunk["id"]],
            "source_chunk_text": chunk["text"],
            "quality": {"critic": "kept"}}


def build_golden_set(docs: list[dict], n_docs: int, per_doc: int, llm) -> list[dict]:
    """Sample docs, drop generic chunks, generate one question per kept chunk up to
    per_doc per document. Returns eval_question-shaped dicts (no ids yet)."""
    rows: list[dict] = []
    for doc in stratified_sample(docs, n_docs):
        kept = [c for c in doc.get("chunks", []) if is_useful_chunk(c)][:per_doc]
        for chunk in kept:
            rows.append(generate_for_chunk(chunk, document_id=doc["id"], llm=llm))
    return rows
