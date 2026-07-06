import pytest
from sqlalchemy.exc import IntegrityError
from madosho_server import db


def _corpus(session, name="c"):
    c = db.Corpus(name=name, config={"corpus": name, "query": []})
    session.add(c); session.commit(); session.refresh(c)
    return c


def _doc(session, corpus, name="f.pdf", h="h"):
    d = db.Document(filename=name, content_hash=h,
                    file_uri="u", mimetype="application/pdf")
    session.add(d); session.commit(); session.refresh(d)
    return d


def test_pipeline_roundtrip_and_defaults(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'p.db'}"); db.create_all()
    with db.SessionLocal() as s:
        c = _corpus(s); d = _doc(s, c)
        p = db.Pipeline(document_id=d.id, name="f_docling",
                        config={"corpus": "c"}, collection="madosho_c_1",
                        slots={"extract": "docling", "chunk": "docling-hybrid",
                               "index": "granite-embedding-english-r2"},
                        is_default=True)
        s.add(p); s.commit(); s.refresh(p)
        assert p.status == "building"          # column default
        assert p.error is None and p.artifacts is None
        assert p.slots["extract"] == "docling"


def test_pipeline_name_unique_within_document(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'u.db'}"); db.create_all()
    with db.SessionLocal() as s:
        c = _corpus(s); d = _doc(s, c)
        s.add(db.Pipeline(document_id=d.id, name="dup", config={}))
        s.commit()
        s.add(db.Pipeline(document_id=d.id, name="dup", config={}))
        with pytest.raises(IntegrityError):
            s.commit()


def test_document_selected_pipeline_id_defaults_none(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'d.db'}"); db.create_all()
    with db.SessionLocal() as s:
        c = _corpus(s); d = _doc(s, c)
        assert d.selected_pipeline_id is None
        d.selected_pipeline_id = 42           # plain int column, app-enforced
        s.commit(); s.refresh(d)
        assert d.selected_pipeline_id == 42
