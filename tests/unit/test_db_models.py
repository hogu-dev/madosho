from madosho_server import db


def test_models_roundtrip_with_json_config(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_all()
    with db.SessionLocal() as session:
        corpus = db.Corpus(name="demo", config={"corpus": "demo", "query": []})
        session.add(corpus)
        session.commit()
        session.refresh(corpus)
        doc = db.Document(filename="a.txt", content_hash="h1",
                          file_uri="h1/a.txt", mimetype="text/plain", status="received")
        session.add(doc)
        session.commit()
        session.refresh(doc)

    with db.SessionLocal() as session:
        got = session.get(db.Document, doc.id)
        assert got.status == "received"
        assert got.error is None


def test_document_stores_artifacts_and_kernel_doc_id(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_all()
    with db.SessionLocal() as session:
        corpus = db.Corpus(name="demo", config={"corpus": "demo", "query": []})
        session.add(corpus)
        session.flush()
        doc = db.Document(
            filename="a.pdf", content_hash="h", file_uri="u",
            mimetype="application/pdf", status="indexed", kernel_doc_id="kdoc-1",
            artifacts={"doc_id": "kdoc-1", "chunks": [{"id": "c1", "text": "hi"}],
                       "blocks": [{"kind": "table", "content": "| a |", "provenance": {"source": "a.pdf"}}]},
        )
        session.add(doc)
        session.commit()
        session.refresh(doc)
        assert doc.kernel_doc_id == "kdoc-1"
        assert doc.artifacts["chunks"][0]["id"] == "c1"
