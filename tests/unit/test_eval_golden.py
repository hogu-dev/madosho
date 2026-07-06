# tests/unit/test_eval_golden.py
"""Grounded Q/A. The generated question's answer key IS the source
chunk; the critic drops generic chunks before generation; sampling is stratified."""
from madosho_server.eval import golden


def _doc(doc_id, traits_type, chunks):
    return {"id": doc_id, "traits": {"doc_type": traits_type}, "chunks": chunks}


def test_critic_drops_generic_chunks():
    assert not golden.is_useful_chunk({"text": "Page 1"})              # too short/generic
    assert not golden.is_useful_chunk({"text": "   "})                 # empty
    assert golden.is_useful_chunk(
        {"text": "The tenant must give ninety days written notice before vacating the unit."})


def test_stratified_sample_spreads_across_doc_types():
    docs = ([_doc(i, "scanned", []) for i in range(5)]
            + [_doc(10 + i, "plain", []) for i in range(5)])
    picked = golden.stratified_sample(docs, n=4)
    types = {d["traits"]["doc_type"] for d in picked}
    assert types == {"scanned", "plain"}     # both strata represented
    assert len(picked) == 4


def test_generate_questions_grounds_answer_key_to_source_chunk():
    chunk = {"id": "c1", "text": "Rent is due on the first of each month.", "page": 2}

    def fake_llm(prompt: str) -> str:
        return "When is rent due?"

    qs = golden.generate_for_chunk(chunk, document_id=7, llm=fake_llm)
    assert qs["question"] == "When is rent due?"
    assert qs["answer_chunk_refs"] == ["c1"]
    assert qs["source_chunk_text"] == "Rent is due on the first of each month."
    assert qs["document_id"] == 7


def test_build_golden_set_filters_then_generates(monkeypatch):
    docs = [{"id": 1, "traits": {"doc_type": "plain"}, "chunks": [
        {"id": "g", "text": "Header"},                                   # dropped by critic
        {"id": "k", "text": "The deposit is refundable within thirty days of move-out."}]}]
    calls = []

    def fake_llm(prompt: str) -> str:
        calls.append(prompt)
        return "What about the deposit?"

    rows = golden.build_golden_set(docs, n_docs=1, per_doc=5, llm=fake_llm)
    assert len(rows) == 1                          # only the useful chunk produced a question
    assert rows[0]["answer_chunk_refs"] == ["k"]
    assert len(calls) == 1                          # critic ran before generation, once
