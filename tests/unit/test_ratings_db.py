# tests/unit/test_ratings_db.py
import pytest
from sqlalchemy.exc import IntegrityError
from madosho_server import db


def _corpus(session, name="c"):
    c = db.Corpus(name=name, config={"corpus": name, "query": []})
    session.add(c); session.commit(); session.refresh(c)
    return c


def test_document_traits_and_corpus_ratings_config_default(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'t.db'}"); db.create_all()
    with db.SessionLocal() as s:
        c = _corpus(s)
        assert c.ratings_config == {"trigger": "on-demand"}      # column default
        doc = db.Document(filename="f.pdf", content_hash="h",
                          file_uri="u", mimetype="application/pdf",
                          traits={"page_count": 3, "text_density": 1800.0})
        s.add(doc); s.commit(); s.refresh(doc)
        assert doc.traits["page_count"] == 3


def test_technique_rating_roundtrip(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'r.db'}"); db.create_all()
    with db.SessionLocal() as s:
        c = _corpus(s)
        doc = db.Document(filename="f.pdf", content_hash="h",
                          file_uri="u", mimetype="application/pdf")
        s.add(doc); s.commit(); s.refresh(doc)
        s.add(db.TechniqueRating(corpus_id=c.id, document_id=doc.id, dimension="embed",
                                 candidate_config="bge-small", score=3.0, source="static",
                                 rationale="clean text", suggestion=None, rater_version="static-v1"))
        s.commit()
        got = s.query(db.TechniqueRating).one()
        assert (got.dimension, got.score, got.source) == ("embed", 3.0, "static")


def test_extraction_comparison_roundtrip(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'x.db'}"); db.create_all()
    with db.SessionLocal() as s:
        c = _corpus(s)
        doc = db.Document(filename="f.pdf", content_hash="h",
                          file_uri="u", mimetype="application/pdf")
        s.add(doc); s.commit(); s.refresh(doc)
        s.add(db.ExtractionComparison(
            document_id=doc.id, engine_a="docling", text_a="A text",
            engine_b="gemma-12b-vision", text_b="B text", judge_model="gemma-e4b",
            judge_verdict="b", judge_score=4.0, judge_confidence=0.8,
            judge_rationale="B is faithful", human_verdict=None))
        s.commit()
        got = s.query(db.ExtractionComparison).one()
        assert got.engine_b == "gemma-12b-vision" and got.judge_verdict == "b"
