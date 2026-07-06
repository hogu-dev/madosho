from madosho.core.types import Chunk, IngestArtifacts
from madosho_server import db, tasks


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'t.db'}")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))
    db.configure_engine(f"sqlite:///{tmp_path/'t.db'}"); db.create_all()


class _FakeCorpus:
    """Records the collection it was opened on; returns fixed artifacts on ingest."""
    def __init__(self, collection):
        self.collection = collection

    def ingest_file(self, sf, reporter=None):
        ch = Chunk(id="k0", doc_id="kdoc", text="hello " * 80, position=0, page=0,
                   metadata={"source": sf.path})
        return IngestArtifacts(doc_id="kdoc", chunks=[ch], blocks=[])


def _seed_doc(tmp_path):
    """A corpus + an uploaded (pre-ingest) document with a real file on disk.
    Also creates the document's default pipeline (as upload now does; H5)."""
    from madosho_server.filestore import FileStore
    from madosho_server.default_config import default_pipeline_config
    with db.SessionLocal() as s:
        c = db.Corpus(name="aero",
                      config=default_pipeline_config("aero", "http://qdrant:6333"))
        s.add(c); s.commit(); s.refresh(c)
        store = FileStore(str(tmp_path / "fs"))
        uri, digest = store.put_stream("contract.pdf", __import__("io").BytesIO(b"%PDF-1.4 x"))
        d = db.Document(filename="contract.pdf", content_hash=digest,
                        file_uri=uri, mimetype="application/pdf", status="received")
        s.add(d); s.flush()
        tasks.create_default_pipeline(s, c, d)   # H5: default pipeline created at upload
        s.commit(); s.refresh(d)
        return c.id, d.id


def test_ingest_creates_and_builds_default_pipeline(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    corpus_id, doc_id = _seed_doc(tmp_path)
    opened = []
    monkeypatch.setattr(tasks, "_open_pipeline_corpus",
                        lambda p, cdir: opened.append(p.collection) or _FakeCorpus(p.collection))
    monkeypatch.setattr(tasks, "count_pdf_pages", lambda path, mime: 1)

    tasks.ingest_document.func(doc_id)        # call the undecorated task body

    with db.SessionLocal() as s:
        doc = s.get(db.Document, doc_id)
        assert doc.status == "indexed"
        assert doc.kernel_doc_id == "kdoc"
        ps = s.query(db.Pipeline).filter_by(document_id=doc_id).all()
        assert len(ps) == 1
        p = ps[0]
        assert p.name == "contract_docling" and p.is_default is True
        assert p.status == "indexed"
        assert p.collection == f"madosho_p{p.id}"
        assert p.config["ingest"]["store"]["qdrant"]["collection"] == p.collection
        assert p.slots["extract"] == "docling"
        named = s.query(db.TechniqueRating).filter_by(candidate_config="contract_docling").count()
        doc_level = s.query(db.TechniqueRating).filter_by(
            document_id=doc_id, candidate_config=None).count()
        assert named == 3 and doc_level == 6
    assert opened == [f"madosho_p{p.id}"]


def test_reingest_reuses_the_default_pipeline(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    corpus_id, doc_id = _seed_doc(tmp_path)
    monkeypatch.setattr(tasks, "_open_pipeline_corpus", lambda p, cdir: _FakeCorpus(p.collection))
    monkeypatch.setattr(tasks, "count_pdf_pages", lambda path, mime: 1)
    tasks.ingest_document.func(doc_id)
    tasks.ingest_document.func(doc_id)        # re-ingest (e.g. via /rebuild)
    with db.SessionLocal() as s:
        assert s.query(db.Pipeline).filter_by(document_id=doc_id).count() == 1
        p = s.query(db.Pipeline).filter_by(document_id=doc_id).one()
        assert p.status == "indexed" and p.kernel_doc_id == "kdoc"


def test_ingest_failure_marks_doc_and_pipeline_failed(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    corpus_id, doc_id = _seed_doc(tmp_path)
    def boom(p, cdir):
        raise RuntimeError("parser exploded")
    monkeypatch.setattr(tasks, "_open_pipeline_corpus", boom)
    monkeypatch.setattr(tasks, "count_pdf_pages", lambda path, mime: 1)
    dropped = []
    monkeypatch.setattr(tasks.eval_runner, "_qdrant_dropper",
                        lambda cdir, rid, cfg: (lambda name: dropped.append(name)))
    tasks.ingest_document.func(doc_id)
    with db.SessionLocal() as s:
        assert s.get(db.Document, doc_id).status == "failed"
        p = s.query(db.Pipeline).filter_by(document_id=doc_id).one()
        assert p.status == "failed" and "exploded" in p.error
    assert dropped == [f"madosho_p{p.id}"]


def test_build_pipeline_indexes_and_rates(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    corpus_id, doc_id = _seed_doc(tmp_path)
    with db.SessionLocal() as s:
        p = db.Pipeline(document_id=doc_id, name="contract_fast",
                        config={"corpus": "aero", "ingest": {}, "query": [],
                                "_collection": "x"}, collection="madosho_aero_99",
                        status="building")
        s.add(p); s.commit(); pid = p.id
    monkeypatch.setattr(tasks, "_open_pipeline_corpus", lambda p, cdir: _FakeCorpus(p.collection))
    tasks.build_pipeline.func(pid)
    with db.SessionLocal() as s:
        p = s.get(db.Pipeline, pid)
        assert p.status == "indexed" and p.kernel_doc_id == "kdoc"
        assert s.query(db.TechniqueRating).filter_by(candidate_config="contract_fast").count() == 3


def test_build_pipeline_failure_marks_failed_and_drops(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    corpus_id, doc_id = _seed_doc(tmp_path)
    with db.SessionLocal() as s:
        p = db.Pipeline(document_id=doc_id, name="bad",
                        config={"corpus": "aero", "ingest": {}, "query": []},
                        collection="madosho_aero_77", status="building")
        s.add(p); s.commit(); pid = p.id
    monkeypatch.setattr(tasks, "_open_pipeline_corpus",
                        lambda p, cdir: (_ for _ in ()).throw(RuntimeError("nope")))
    dropped = []
    monkeypatch.setattr(tasks.eval_runner, "_qdrant_dropper",
                        lambda cdir, rid, cfg: (lambda name: dropped.append(name)))
    tasks.build_pipeline.func(pid)
    with db.SessionLocal() as s:
        p = s.get(db.Pipeline, pid)
        assert p.status == "failed" and "nope" in p.error
    assert dropped == ["madosho_aero_77"]


def test_delete_artifacts_drops_each_pipeline_collection(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    dropped = []
    monkeypatch.setattr(tasks.eval_runner, "_qdrant_dropper",
                        lambda cdir, rid, cfg: (lambda name: dropped.append(name)))
    tasks.delete_document_artifacts.func(
        collections=["madosho_c_3", "madosho_c_4"], file_uri="missing")
    assert sorted(dropped) == ["madosho_c_3", "madosho_c_4"]
