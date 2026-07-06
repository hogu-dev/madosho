import procrastinate

from madosho.core.types import Chunk, IngestArtifacts
from madosho_server import db, tasks


class _FakeCorpus:
    """Minimal stand-in for the kernel corpus, returns minimal artifacts."""
    def ingest_file(self, sf, reporter=None):
        return IngestArtifacts(
            doc_id="kdoc-w1",
            chunks=[Chunk(id="c1", doc_id="kdoc-w1", text="alpha beta gamma delta",
                          position=0, page=0)],
            blocks=[],
        )


def _fake_config(name):
    return {"corpus": name,
            "ingest": {"parser": "fake-parser", "chunker": "fake-chunker",
                       "embedder": "hash-embedder", "store": "fake-store",
                       "indexes": ["bm25", "dense"]},
            "query": []}


def test_ingest_document_marks_indexed(tmp_path, monkeypatch):
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))
    db.configure_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_all()
    tasks.reset_corpus_cache()

    # a file in the store
    from madosho_server.filestore import FileStore
    store = FileStore(tmp_path / "fs")
    f = tmp_path / "doc.txt"
    f.write_text("alpha beta\n\ngamma delta")
    with open(f, "rb") as fh:
        uri, digest = store.put_stream("doc.txt", fh)

    # a corpus + a received document row + default pipeline (H5: created at upload)
    with db.SessionLocal() as s:
        corpus = db.Corpus(name="demo", config=_fake_config("demo"))
        s.add(corpus); s.flush()
        doc = db.Document(filename="doc.txt", content_hash=digest,
                          file_uri=uri, mimetype="text/plain", status="received")
        s.add(doc); s.flush()
        tasks.create_default_pipeline(s, corpus, doc)  # H5: default pipeline created at upload
        s.commit(); doc_id = doc.id

    monkeypatch.setattr(tasks, "_open_pipeline_corpus", lambda pipeline, cd: _FakeCorpus())

    # run the task via the in-memory queue
    in_memory = procrastinate.testing.InMemoryConnector()
    tasks.use_connector(in_memory)
    with tasks.app.open():
        tasks.ingest_document.defer(document_id=doc_id)
        tasks.app.run_worker(wait=False, queues=["ingest"], install_signal_handlers=False)

    with db.SessionLocal() as s:
        assert s.get(db.Document, doc_id).status == "indexed"


def test_ingest_document_missing_pipeline_marks_failed(tmp_path, monkeypatch):
    """H5: ingest_document no longer does a corpus lookup; it looks for the doc's
    default pipeline (created at upload). A doc with no pipeline fails gracefully.
    This replaces the old 'missing corpus' test: with H5, ingest never reads corpus_id."""
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))
    db.configure_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_all()
    tasks.reset_corpus_cache()

    # a received document with no pipeline row — simulates an orphan or a pre-H5 doc
    with db.SessionLocal() as s:
        doc = db.Document(filename="x.txt", content_hash="h",
                          file_uri="h/x.txt", mimetype="text/plain", status="received")
        s.add(doc); s.commit(); s.refresh(doc)
        doc_id = doc.id

    in_memory = procrastinate.testing.InMemoryConnector()
    tasks.use_connector(in_memory)
    with tasks.app.open():
        tasks.ingest_document.defer(document_id=doc_id)
        tasks.app.run_worker(wait=False, queues=["ingest"], install_signal_handlers=False)

    with db.SessionLocal() as s:
        got = s.get(db.Document, doc_id)
        assert got.status == "failed"          # failure branch ran and committed
        assert got.error and "no default pipeline" in got.error  # H5: corpus lookup gone
