"""Task 3: worker persists IngestArtifacts (kernel_doc_id + artifacts JSON)."""
import procrastinate
import procrastinate.testing

from madosho.core.types import Block, BlockKind, Chunk, IngestArtifacts, Provenance
from madosho_server import db, tasks

_BASE_CONFIG = {
    "corpus": "demo",
    "ingest": {"parser": "fake-parser", "chunker": "fake-chunker",
               "embedder": "hash-embedder", "store": "fake-store",
               "indexes": ["bm25", "dense"]},
    "query": [],
}


class _FakeCorpus:
    def ingest_file(self, sf, reporter=None):
        return IngestArtifacts(
            doc_id="kdoc-7",
            chunks=[Chunk(id="c1", doc_id="kdoc-7", text="hello", position=0, page=1)],
            blocks=[Block(kind=BlockKind.TABLE, content="| a | b |",
                          provenance=Provenance(source="a.pdf", page=1))],
        )


def test_ingest_persists_artifacts_and_kernel_doc_id(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 't.db'}")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))
    db.configure_engine(f"sqlite:///{tmp_path / 't.db'}")
    db.create_all()
    (tmp_path / "fs").mkdir()
    tasks.reset_corpus_cache()

    with db.SessionLocal() as s:
        c = db.Corpus(name="demo", config={"corpus": "demo", "query": []})
        s.add(c); s.flush()
        d = db.Document(filename="a.pdf", content_hash="h",
                        file_uri="h/a.pdf", mimetype="application/pdf", status="received")
        s.add(d); s.flush()
        tasks.create_default_pipeline(s, c, d)   # H5: default pipeline created at upload
        s.commit(); doc_id = d.id

    monkeypatch.setattr(tasks, "_open_pipeline_corpus", lambda pipeline, cd: _FakeCorpus())
    monkeypatch.setattr(tasks.FileStore, "path_for", lambda self, uri: tmp_path / "fs" / "a.pdf")

    # invoke via Procrastinate's in-memory queue (same pattern as test_worker_task.py)
    in_memory = procrastinate.testing.InMemoryConnector()
    tasks.use_connector(in_memory)
    with tasks.app.open():
        tasks.ingest_document.defer(document_id=doc_id)
        tasks.app.run_worker(wait=False, queues=["ingest"], install_signal_handlers=False)

    with db.SessionLocal() as s:
        d = s.get(db.Document, doc_id)
        assert d.status == "indexed"
        assert d.kernel_doc_id == "kdoc-7"
        assert d.artifacts["chunks"][0]["text"] == "hello"
        assert d.artifacts["blocks"][0]["kind"] == "table"


def test_corpus_for_tasks_reopens_on_config_change(tmp_path, monkeypatch):
    """tasks._corpus_for must evict and reopen when the corpus config changes."""
    corpora = []

    class _SimpleCorpus:
        pass

    def fake_open(cfg, data_dir, registry=None):
        obj = _SimpleCorpus()
        corpora.append(obj)
        return obj

    monkeypatch.setattr(tasks, "open_corpus_from_config", fake_open)
    # MadoshoConfig validation would reject fake component names; bypass by
    # patching it to a passthrough so the hash-then-open logic still runs.
    monkeypatch.setattr(tasks, "MadoshoConfig", lambda **kw: kw)
    tasks.reset_corpus_cache()

    row = db.Corpus(name="demo", config=dict(_BASE_CONFIG))
    row.id = 99

    c1 = tasks._corpus_for(row, str(tmp_path))
    c1_again = tasks._corpus_for(row, str(tmp_path))
    assert c1 is c1_again      # same config -> still cached
    assert len(corpora) == 1

    # Swap chunker (simulates Apply or PUT /config)
    row.config = dict(_BASE_CONFIG)
    row.config["ingest"] = dict(row.config["ingest"])
    row.config["ingest"]["chunker"] = "new-chunker"

    c2 = tasks._corpus_for(row, str(tmp_path))
    assert c2 is not c1        # reopened on config change
    assert len(corpora) == 2

    # Cache must not grow unbounded
    assert len(tasks._CORPUS_CACHE) == 1

    # Another call with new config returns same object, no extra open
    c2_again = tasks._corpus_for(row, str(tmp_path))
    assert c2_again is c2
    assert len(corpora) == 2
