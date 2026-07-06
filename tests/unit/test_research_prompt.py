# tests/unit/test_research_prompt.py
"""The prompt the worker composes to steer source/target.
Pure string logic - no DB, no network."""
from madosho_server.research import compose_research_prompt


def test_rag_whole_corpus_names_corpus_and_question():
    p = compose_research_prompt(
        "How are sensor failures handled?", "aerospace",
        source="rag", document_ids=[], budget_chars=100000)
    assert "aerospace" in p
    assert "How are sensor failures handled?" in p
    assert "search" in p.lower()


def test_whole_text_lists_target_document_ids():
    p = compose_research_prompt(
        "Summarize the manual.", "aerospace",
        source="whole-text", document_ids=[3, 7], budget_chars=100000)
    assert "get-doc" in p.lower()
    assert "3" in p and "7" in p
    # whole-text must mention the budget fallback to search
    assert "fall back" in p.lower() or "budget" in p.lower()


def test_rag_with_selected_docs_hints_focus():
    p = compose_research_prompt(
        "What changed?", "aerospace",
        source="rag", document_ids=[5], budget_chars=50000)
    assert "5" in p
    assert "aerospace" in p
