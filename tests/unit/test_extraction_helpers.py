# tests/unit/test_extraction_helpers.py
from pathlib import Path

import pytest
from madosho_server.extraction import (
    select_judge, verdict_to_score, _docling_text, _parse_verdict, render_page_images,
    _docling_pages)


def test_docling_pages_groups_by_provenance_page():
    artifacts = {"blocks": [
        {"content": "Title", "provenance": {"page": 1}},
        {"content": "Body one", "provenance": {"page": 1}},
        {"content": "Body two", "provenance": {"page": 2}},
    ]}
    pages = _docling_pages(artifacts)
    assert pages[1] == "Title\n\nBody one"
    assert pages[2] == "Body two"


def test_judge_must_not_have_made_either_conversion():
    judges = [{"engine": "gemma-12b-vision", "provider": "p", "model": "m12"},
              {"engine": "gemma-e4b", "provider": "p", "model": "m4"}]
    j = select_judge("docling", "gemma-12b-vision", judges)
    assert j["engine"] == "gemma-e4b"             # 12b excluded (it made a conversion)


def test_vision_vs_vision_leaves_no_judge():
    judges = [{"engine": "gemma-12b-vision", "provider": "p", "model": "m"}]
    assert select_judge("gemma-12b-vision", "gemma-e4b", judges) is None  # human-only path


def test_verdict_to_score_uses_winner_faithfulness_clamped():
    assert verdict_to_score({"winner_faithfulness": 4.2}) == 4.2
    assert verdict_to_score({"winner_faithfulness": 9.0}) == 5.0
    assert verdict_to_score({"winner_faithfulness": -1.0}) == 0.0
    assert verdict_to_score({}) == 0.0


def test_docling_text_prefers_blocks_and_decodes_pipe_entities():
    # The docling pane is the head-to-head's "structure" side: a faithfulness judge
    # must see the table GRID, which only the structured blocks preserve. Chunk text
    # is retrieval-tuned and flattens tables, so blocks win when present.
    artifacts = {
        "blocks": [
            {"kind": "heading", "content": "Stage Specs", "provenance": {"page": 1}},
            {"kind": "table",
             "content": "| Thrust &#124; kN | Mass |\n| --- | --- |\n| 100 | 2 |",
             "provenance": {"page": 1}},
        ],
        "chunks": [{"text": "thrust kN mass flattened", "page": 0}],
    }
    out = _docling_text(artifacts)
    assert "Stage Specs" in out          # heading block kept, in reading order
    assert "Thrust | kN" in out          # &#124; decoded back to a literal pipe
    assert "---" in out                  # table grid survives (chunks would flatten it)
    assert "flattened" not in out        # chunk text NOT used when blocks exist


def test_docling_text_falls_back_to_chunks_when_no_blocks():
    # Older artifact sets (pre-blocks) only have chunks; keep working for them.
    artifacts = {"blocks": [], "chunks": [{"text": "chunk a"}, {"text": "chunk b"}]}
    assert _docling_text(artifacts) == "chunk a\n\nchunk b"


def test_docling_text_handles_empty_or_missing_artifacts():
    assert _docling_text(None) == ""
    assert _docling_text({}) == ""


def test_parse_verdict_bare_json():
    assert _parse_verdict('{"verdict":"a","winner_faithfulness":4}')["verdict"] == "a"


def test_parse_verdict_json_fence():
    raw = '```json\n{"verdict":"b","winner_faithfulness":5}\n```'
    assert _parse_verdict(raw)["verdict"] == "b"


def test_parse_verdict_bare_fence():
    raw = '```\n{"verdict":"tie","winner_faithfulness":3}\n```'
    assert _parse_verdict(raw)["verdict"] == "tie"


def test_parse_verdict_prose_wrapped():
    raw = 'Here is my answer:\n{"verdict":"a","winner_faithfulness":2}\nThanks!'
    assert _parse_verdict(raw)["winner_faithfulness"] == 2


def test_parse_verdict_unparseable_raises():
    with pytest.raises(ValueError):
        _parse_verdict("I cannot decide. No JSON here.")


def _make_pdf(path: Path, pages: int) -> Path:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
    pdf = FPDF()
    for i in range(pages):
        pdf.add_page()
        pdf.set_font("helvetica", size=14)
        pdf.cell(0, 10, f"Page {i + 1} content", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.output(str(path))
    return path


def test_render_page_images_one_per_page(tmp_path):
    pdf = _make_pdf(tmp_path / "two.pdf", 2)
    imgs = render_page_images(str(pdf))
    assert [n for n, _ in imgs] == [1, 2]
    assert all(isinstance(b, bytes) and b[:8] == b"\x89PNG\r\n\x1a\n" for _, b in imgs)


def test_render_page_images_caps_and_logs(tmp_path, caplog):
    pdf = _make_pdf(tmp_path / "three.pdf", 3)
    import logging
    with caplog.at_level(logging.WARNING):
        imgs = render_page_images(str(pdf), max_pages=1)
    assert [n for n, _ in imgs] == [1]
    assert any("max_pages" in r.message or "truncat" in r.message.lower()
               for r in caplog.records)


import types
import madosho_server.extraction as extraction
from madosho_server.settings import Settings


def _settings(tmp_path):
    return Settings(database_url="sqlite://", qdrant_url="", filestore_dir=str(tmp_path),
                    corpora_dir=str(tmp_path), llm_api_base="http://vision", llm_api_key=None)


def _fake_resp(text):
    msg = types.SimpleNamespace(content=text)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])


def test_vision_transcribe_sends_image_and_returns_pages(tmp_path, monkeypatch):
    # store a real 1-page pdf through the filestore so file_uri resolves
    from madosho_server.filestore import FileStore
    pdf = _make_pdf(tmp_path / "src.pdf", 1)
    store = FileStore(str(tmp_path))
    with open(pdf, "rb") as fh:
        uri, _digest = store.put_stream("src.pdf", fh)
    doc = types.SimpleNamespace(file_uri=uri, mimetype="application/pdf")

    seen = {}
    def fake_complete(messages, provider, model, settings, stream=False):
        seen["messages"] = messages
        return _fake_resp("PAGE ONE TEXT")
    monkeypatch.setattr(extraction, "complete", fake_complete)

    pages = extraction.vision_transcribe(doc, "openai", "gemma-4-e4b", _settings(tmp_path))
    assert pages == [(1, "PAGE ONE TEXT")]
    parts = seen["messages"][0]["content"]
    assert any(p.get("type") == "image_url" and
               p["image_url"]["url"].startswith("data:image/png;base64,") for p in parts)


def test_vision_transcribe_non_pdf_returns_empty(tmp_path, monkeypatch):
    doc = types.SimpleNamespace(file_uri="whatever", mimetype="text/plain")
    monkeypatch.setattr(extraction, "complete",
                        lambda *a, **k: _fake_resp("nope"))
    assert extraction.vision_transcribe(doc, "openai", "m", _settings(tmp_path)) == []


def test_vision_transcribe_responses_flavor_uses_respond(tmp_path, monkeypatch):
    from madosho_server.filestore import FileStore
    pdf = _make_pdf(tmp_path / "src.pdf", 1)
    store = FileStore(str(tmp_path))
    with open(pdf, "rb") as fh:
        uri, _digest = store.put_stream("src.pdf", fh)
    doc = types.SimpleNamespace(file_uri=uri, mimetype="application/pdf")

    seen = {}
    def fake_respond(input_data, provider, model, settings):
        seen["input_data"] = input_data
        return "RESPONSES PAGE TEXT"
    monkeypatch.setattr(extraction, "respond", fake_respond)
    monkeypatch.setattr(extraction, "complete",
                        lambda *a, **k: pytest.fail("chat path used for responses flavor"))

    pages = extraction.vision_transcribe(doc, "openai", "gpt-5.5",
                                         _settings(tmp_path), api_flavor="responses")
    assert pages == [(1, "RESPONSES PAGE TEXT")]
    parts = seen["input_data"][0]["content"]
    assert parts[0]["type"] == "input_text"
    assert any(p.get("type") == "input_image" and p["detail"] == "auto" and
               p["image_url"].startswith("data:image/png;base64,") for p in parts)


def test_judge_call_responses_flavor_uses_respond(monkeypatch):
    monkeypatch.setattr(extraction, "respond",
                        lambda *a, **k: '{"verdict":"b","winner_faithfulness":4,'
                                        '"confidence":0.9,"rationale":"r"}')
    monkeypatch.setattr(extraction, "complete",
                        lambda *a, **k: pytest.fail("chat path used for responses flavor"))
    verdict = extraction.judge_call("a", "b", "openai", "gpt-5.5",
                                    _settings("/tmp"), api_flavor="responses")
    assert verdict["verdict"] == "b"
