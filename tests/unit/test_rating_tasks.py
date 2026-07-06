# tests/unit/test_rating_tasks.py
import procrastinate
import procrastinate.testing

from madosho.core.types import Block, BlockKind, Chunk, IngestArtifacts, Provenance
from madosho_server import db, tasks


class _FakeCorpus:
    def ingest_file(self, sf, reporter=None):
        return IngestArtifacts(
            doc_id="kdoc-e1",
            chunks=[Chunk(id="c1", doc_id="kdoc-e1", text="x" * 1800, position=0, page=0)],
            blocks=[Block(kind=BlockKind.TABLE, content="| a | b |",
                          provenance=Provenance(source="f.pdf", page=0))],
        )


def _seed(tmp_path, trigger="on-demand"):
    db.configure_engine(f"sqlite:///{tmp_path/'w.db'}"); db.create_all()
    with db.SessionLocal() as s:
        c = db.Corpus(name="c", config={"corpus": "c"}, ratings_config={"trigger": trigger})
        s.add(c); s.commit(); s.refresh(c)
        doc = db.Document(filename="f.pdf", content_hash="h", file_uri="u",
                          mimetype="application/pdf",
                          artifacts={"chunks": [{"text": "x" * 1800, "page": 0}], "blocks": []})
        doc.status = "indexed"
        s.add(doc); s.commit(); s.refresh(doc)
        return c.id, doc.id


def test_rate_document_persists_traits_and_static_cube(tmp_path):
    cid, did = _seed(tmp_path)
    with db.SessionLocal() as s:
        tasks.rate_document(s, did)
        s.commit()
        doc = s.get(db.Document, did)
        assert doc.traits["text_density"] == 1800.0
        dims = {r.dimension for r in s.query(db.TechniqueRating).filter_by(document_id=did)}
        assert dims == {"extraction", "chunk", "embed", "keyword", "semantic", "rerank"}


def test_rate_document_is_idempotent_replaces_static_rows(tmp_path):
    cid, did = _seed(tmp_path)
    with db.SessionLocal() as s:
        tasks.rate_document(s, did); s.commit()

        # Insert a measured row to verify it is NOT deleted on re-rate.
        s.add(db.TechniqueRating(corpus_id=cid, document_id=did,
                                 dimension="extraction", source="measured",
                                 score=0.9, rationale="live"))
        s.commit()

        tasks.rate_document(s, did); s.commit()           # re-rate
        n = s.query(db.TechniqueRating).filter_by(document_id=did, source="static").count()
        assert n == 6                                     # not 12 - old static rows cleared
        m = s.query(db.TechniqueRating).filter_by(document_id=did, source="measured").count()
        assert m == 1                                     # measured row untouched


def test_on_ingest_trigger_does_not_auto_enqueue_extraction_comparison(tmp_path, monkeypatch):
    """H5/H8: the on-ingest auto-trigger for extraction comparison is dropped from
    ingest_document. A shared document belongs to many corpora; "the" corpus to run
    the comparison for is ambiguous. The comparison still runs on-demand via its
    endpoint (unchanged). This test asserts the trigger does NOT fire.
    (Previously asserted the trigger DID fire; removed per H8 provisional design.)"""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'e.db'}")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))

    db.configure_engine(f"sqlite:///{tmp_path / 'e.db'}")
    db.create_all()
    (tmp_path / "fs").mkdir()
    tasks.reset_corpus_cache()

    with db.SessionLocal() as s:
        c = db.Corpus(name="e", config={"corpus": "e", "query": []},
                      ratings_config={"trigger": "on-ingest"})
        s.add(c); s.flush()
        d = db.Document(filename="f.pdf", content_hash="h",
                        file_uri="h/f.pdf", mimetype="application/pdf", status="received")
        s.add(d); s.flush()
        tasks.create_default_pipeline(s, c, d)   # H5: default pipeline created at upload
        s.commit(); doc_id = d.id

    monkeypatch.setattr(tasks, "_open_pipeline_corpus", lambda pipeline, cd: _FakeCorpus())
    monkeypatch.setattr(tasks.FileStore, "path_for", lambda self, uri: tmp_path / "fs" / "f.pdf")

    deferred_tasks: list[str] = []

    class _FakeDeferrer:
        def defer(self, **kwargs):
            deferred_tasks.append("run_extraction_comparison")

    def _fake_configure(**kwargs):
        return _FakeDeferrer()

    monkeypatch.setattr(tasks.run_extraction_comparison_task, "configure", _fake_configure)

    in_memory = procrastinate.testing.InMemoryConnector()
    tasks.use_connector(in_memory)
    with tasks.app.open():
        tasks.ingest_document.defer(document_id=doc_id)
        tasks.app.run_worker(wait=False, queues=["ingest"], install_signal_handlers=False)

    with db.SessionLocal() as s:
        d = s.get(db.Document, doc_id)
        assert d.status == "indexed"

    # H8: the on-ingest trigger is removed; comparison must NOT be auto-deferred
    assert "run_extraction_comparison" not in deferred_tasks
