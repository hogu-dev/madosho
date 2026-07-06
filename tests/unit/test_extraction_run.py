# tests/unit/test_extraction_run.py
import pytest
from madosho_server import db
from madosho_server.extraction import run_extraction_comparison
from madosho_server.settings import Settings


def _settings():
    return Settings(database_url="sqlite://", qdrant_url="", filestore_dir="/tmp",
                    corpora_dir="/tmp", llm_api_base="http://vision", llm_api_key=None)


def _seed_doc(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'e.db'}"); db.create_all()
    with db.SessionLocal() as s:
        c = db.Corpus(name="c", config={"corpus": "c"}); s.add(c); s.commit(); s.refresh(c)
        doc = db.Document(filename="f.pdf", content_hash="h", file_uri="u",
                          mimetype="application/pdf",
                          artifacts={"chunks": [{"text": "docling text here", "page": 0}], "blocks": []})
        s.add(doc); s.commit(); s.refresh(doc)
        return c.id, doc.id


def _resolve_ok(session, settings):
    return ("openai", "gemma-4-e4b", settings, "chat")


def test_run_writes_comparison_and_measured_rating(tmp_path):
    cid, did = _seed_doc(tmp_path)
    def fake_vision(doc, provider, model, settings, api_flavor="chat"):
        return [(1, "vision text there")]
    def fake_judge(text_a, text_b, provider, model, settings, api_flavor="chat"):
        return {"verdict": "b", "winner_faithfulness": 4.0, "confidence": 0.9, "rationale": "B wins"}

    with db.SessionLocal() as s:
        run_extraction_comparison(s, did, _settings(),
                                  vision_transcribe=fake_vision, judge_call=fake_judge,
                                  resolve_vision=_resolve_ok)
        s.commit()
        comp = s.query(db.ExtractionComparison).one()
        assert comp.engine_a == "docling"
        assert comp.engine_b == "gemma-4-e4b (vision)"   # resolved model, not the old literal
        assert comp.judge_model == "gemma-4-e4b" and comp.judge_verdict == "b"
        assert comp.pages and comp.pages[0]["text_b"] == "vision text there"
        rating = s.query(db.TechniqueRating).filter_by(dimension="extraction", source="measured").one()
        assert rating.score == 4.0 and rating.document_id == did


def test_run_fails_loud_without_vision_endpoint(tmp_path):
    cid, did = _seed_doc(tmp_path)
    from madosho_server.extraction import VisionEndpointUnavailable
    with db.SessionLocal() as s:
        with pytest.raises(VisionEndpointUnavailable):
            run_extraction_comparison(s, did, _settings(),
                                      vision_transcribe=lambda *a, **k: "v",
                                      judge_call=lambda *a, **k: {"verdict": "a"},
                                      resolve_vision=lambda se, st: None)
