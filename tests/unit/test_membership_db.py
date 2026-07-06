from madosho_server import db


def _mk(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'h.db'}")
    db.create_all()
    return db.SessionLocal()


def test_document_corpus_join_table_exists_and_is_unique(tmp_path):
    s = _mk(tmp_path)
    c = db.Corpus(name="c", config={})
    s.add(c); s.commit(); s.refresh(c)
    d = db.Document(filename="a.pdf", content_hash="h1",
                    file_uri="u", mimetype="application/pdf")
    s.add(d); s.commit(); s.refresh(d)
    s.add(db.DocumentCorpus(document_id=d.id, corpus_id=c.id)); s.commit()
    rows = s.query(db.DocumentCorpus).all()
    assert len(rows) == 1 and rows[0].added_at is not None
    # duplicate (document_id, corpus_id) is rejected
    import pytest
    from sqlalchemy.exc import IntegrityError
    s.add(db.DocumentCorpus(document_id=d.id, corpus_id=c.id))
    with pytest.raises(IntegrityError):
        s.commit()
    s.rollback()


def test_document_has_no_corpus_id_and_pipeline_unique_per_document(tmp_path):
    from sqlalchemy import inspect
    s = _mk(tmp_path)
    cols = {c["name"] for c in inspect(db.engine).get_columns("document")}
    assert "corpus_id" not in cols
    pcols = {c["name"] for c in inspect(db.engine).get_columns("pipeline")}
    assert "corpus_id" not in pcols
    # same pipeline name allowed on different documents; rejected on the same one
    c = db.Corpus(name="c", config={}); s.add(c); s.commit(); s.refresh(c)
    import pytest
    from sqlalchemy.exc import IntegrityError
    d1 = db.Document(filename="a.pdf", content_hash="h1", file_uri="u",
                     mimetype="application/pdf")
    d2 = db.Document(filename="b.pdf", content_hash="h2", file_uri="u",
                     mimetype="application/pdf")
    s.add_all([d1, d2]); s.commit()
    s.add(db.Pipeline(document_id=d1.id, name="p", config={}))
    s.add(db.Pipeline(document_id=d2.id, name="p", config={}))   # same name, diff doc: OK
    s.commit()
    s.add(db.Pipeline(document_id=d1.id, name="p", config={}))   # dup on same doc
    with pytest.raises(IntegrityError):
        s.commit()
    s.rollback()
